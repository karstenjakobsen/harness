import shutil
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.memory import create_connected_server_and_client_session

from harness_api import (
    GoalAPI,
    OperatorAPI,
    SkillAPI,
    SkillCatalog,
    SkillReference,
    SkillSource,
    WorkAPI,
    WorkspaceInput,
)
from harness_mcp.server import create_server
from harness_mcp.worker import create_worker_app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def worker(tmp_path):
    path = tmp_path / "selected-workspace.db"
    goal = GoalAPI(path).create_goal("Create cities.txt", status="active")
    operator = OperatorAPI(path).register_operator("Worker")
    manifest = (
        "kind: skill\nid: handoff\nrevision: 1\nname: Handoff\n"
        "description: Save the requested file\nauthor: Owner\n"
    )
    skills = SkillAPI(path)
    skills.import_catalog(
        SkillCatalog(
            "a" * 40,
            (SkillSource("skills/handoff", manifest, "Submit the requested file."),),
        )
    )
    work = WorkAPI(path)
    item = work.create_work_item(
        goal["id"],
        goal["revision"],
        operator["id"],
        "Write Aalborg, Aarhus, Copenhagen, Odense and Roskilde to cities.txt.",
        skills=[SkillReference(id="handoff", revision=1)],
    )
    # An update to the catalog does not update this attempt's assignment.
    skills.import_catalog(
        SkillCatalog(
            "b" * 40,
            (
                SkillSource(
                    "skills/handoff",
                    manifest.replace("revision: 1", "revision: 2"),
                    "New instructions for a later assignment.",
                ),
            ),
        )
    )
    attempt = work.create_attempt("city-worker", item["id"])
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    work.set_scratch(attempt["id"], scratch)
    work.grant_attempt(attempt["id"], "city-credential")
    return path, work, item, attempt, scratch


@asynccontextmanager
async def worker_http(work):
    app = create_worker_app(work)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://127.0.0.1:8001",
        ) as client,
    ):
        yield client


@asynccontextmanager
async def worker_session(work, credential="city-credential"):
    async with worker_http(work) as http:
        http.headers["Authorization"] = f"Bearer {credential}"
        async with (
            streamable_http_client("http://127.0.0.1:8001/mcp", http_client=http) as (
                reader,
                writer,
                session_id,
            ),
            ClientSession(reader, writer, timedelta(seconds=5)) as session,
        ):
            await session.initialize()
            yield session, http, session_id


async def request(client, method, params=None, credential="city-credential"):
    headers = {"Accept": "application/json, text/event-stream"}
    if credential is not None:
        headers["Authorization"] = f"Bearer {credential}"
    return await client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )


@pytest.mark.anyio
async def test_worker_protocol_reads_exact_assignment_and_saves_durable_result(worker):
    path, work, item, attempt, scratch = worker
    content = b"Aalborg\nAarhus\nCopenhagen\nOdense\nRoskilde\n"
    (scratch / "cities.txt").write_bytes(content)
    async with worker_session(work) as (session, _, session_id):
        assert session_id() is None
        tools = (await session.list_tools()).tools
        assert {tool.name for tool in tools} == {
            "get_work_brief",
            "list_skills",
            "read_skill",
            "submit_work_result",
        }
        assert all(tool.inputSchema["additionalProperties"] is False for tool in tools)
        submission = next(tool for tool in tools if tool.name == "submit_work_result")
        assert set(submission.inputSchema["properties"]) == {"relative_path"}
        brief = (await session.call_tool("get_work_brief", {})).structuredContent
        assert brief["attempt_id"] == attempt["id"]
        assert brief["work_item"] == item
        assert brief["goal"]["revision"] == 1
        listed = (await session.call_tool("list_skills", {})).structuredContent
        assert [(s["id"], s["revision"]) for s in listed["skills"]] == [("handoff", 1)]
        skill = await session.call_tool("read_skill", {"id": "handoff", "revision": 1})
        assert skill.structuredContent["instructions"] == "Submit the requested file."
        saved = await session.call_tool(
            "submit_work_result", {"relative_path": "cities.txt"}
        )
        assert not saved.isError, saved.content
        artifact = saved.structuredContent
        (scratch / "cities.txt").write_text("Changed after the first save")
        assert (
            await session.call_tool(
                "submit_work_result", {"relative_path": "cities.txt"}
            )
        ).structuredContent == artifact
        shutil.rmtree(scratch)
        work.mark_scratch_cleaned(attempt["id"])
        assert (
            await session.call_tool(
                "submit_work_result", {"relative_path": "cities.txt"}
            )
        ).structuredContent == artifact
        assert (
            await session.call_tool(
                "submit_work_result", {"relative_path": "other.txt"}
            )
        ).isError
    owner = WorkAPI(path)
    assert owner.list_artifacts(item["goal_id"]) == [artifact]
    assert owner.read_artifact_bytes(artifact["id"]) == content
    assert artifact["operator_id"] == item["operator_id"]
    assert artifact["goal_revision"] == 1
    assert GoalAPI(path).get_goal(item["goal_id"])["status"] == "active"
    calls = owner.list_worker_calls(attempt["id"])
    assert [call["tool"] for call in calls] == [
        "tools/list",
        "get_work_brief",
        "list_skills",
        "read_skill",
        "submit_work_result",
        "submit_work_result",
        "submit_work_result",
        "submit_work_result",
    ]
    assert [call["outcome"] for call in calls] == ["returned"] * 7 + ["denied"]


@pytest.mark.anyio
async def test_every_http_request_requires_a_valid_worker_credential(worker):
    _, work, _, _, _ = worker
    async with worker_http(work) as http:
        for method, params in (
            (
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            ),
            ("tools/list", {}),
            (
                "tools/call",
                {
                    "name": "submit_work_result",
                    "arguments": {"relative_path": "cities.txt"},
                },
            ),
        ):
            for credential in (None, "invalid-credential"):
                response = await request(http, method, params, credential)
                assert response.status_code == 401
                assert response.headers["WWW-Authenticate"].startswith("Bearer")


@pytest.mark.anyio
async def test_worker_cannot_supply_identity_or_use_unassigned_tools_and_revisions(
    worker,
):
    _, work, item, attempt, _ = worker
    other = work.create_attempt("other-worker", item["id"])
    work.grant_attempt(other["id"], "other-credential")
    async with worker_session(work) as (session, http, session_id):
        for name, arguments in (
            ("get_work_brief", {"attempt_id": other["id"]}),
            (
                "submit_work_result",
                {"relative_path": "cities.txt", "credential": "other-credential"},
            ),
            ("submit_work_result", {"relative_path": "../outside"}),
            ("read_skill", {"id": "handoff", "revision": True}),
            ("read_skill", {"id": "handoff", "revision": 2}),
            ("read_skill", {"id": "unassigned", "revision": 1}),
            ("complete_goal", {"goal_id": item["goal_id"]}),
        ):
            result = await session.call_tool(name, arguments)
            assert result.isError, (name, result)
        assert work.get_attempt(attempt["id"])["artifact_id"] is None
        # There is no persistent transport session that could leak the old attempt.
        assert session_id() is None
        http.headers["Authorization"] = "Bearer other-credential"
        brief = (await session.call_tool("get_work_brief", {})).structuredContent
        assert brief["attempt_id"] == other["id"]
        assert [c["outcome"] for c in work.list_worker_calls(attempt["id"])] == [
            "denied"
        ] * 7
        calls = work.list_worker_calls(other["id"])
        assert any(call["tool"] == "get_work_brief" for call in calls)
        assert all(call["outcome"] == "returned" for call in calls)


@pytest.mark.anyio
async def test_withdrawn_and_rotated_tokens_cannot_discover_or_retry_saved_results(
    worker,
):
    _, work, _, attempt, scratch = worker
    (scratch / "result.txt").write_text("Saved once")
    async with worker_session(work) as (session, http, _):
        artifact = (
            await session.call_tool(
                "submit_work_result", {"relative_path": "result.txt"}
            )
        ).structuredContent
        work.revoke_attempt_grant(attempt["id"])
        work.grant_attempt(attempt["id"], "replacement-credential")
        for method, params in (
            ("tools/list", {}),
            (
                "tools/call",
                {
                    "name": "submit_work_result",
                    "arguments": {"relative_path": "result.txt"},
                },
            ),
        ):
            assert (await request(http, method, params)).status_code == 401
        replacement = await request(
            http,
            "tools/call",
            {
                "name": "submit_work_result",
                "arguments": {"relative_path": "result.txt"},
            },
            "replacement-credential",
        )
        assert replacement.json()["result"]["structuredContent"] == artifact
    assert work.read_artifact_bytes(artifact["id"]) == b"Saved once"
    assert (
        sum(c["outcome"] == "denied" for c in work.list_worker_calls(attempt["id"]))
        == 2
    )


@pytest.mark.anyio
async def test_advisory_mcp_cannot_discover_or_invoke_worker_tools(worker):
    path, work, _, attempt, _ = worker
    advisory = create_server(GoalAPI(path))
    async with create_connected_server_and_client_session(advisory) as session:
        tools = {tool.name for tool in (await session.list_tools()).tools}
        assert tools.isdisjoint({"get_work_brief", "submit_work_result"})
        for name, arguments in (
            ("get_work_brief", {}),
            ("submit_work_result", {"relative_path": "cities.txt"}),
        ):
            assert (await session.call_tool(name, arguments)).isError
    assert work.list_worker_calls(attempt["id"]) == []
    assert work.get_attempt(attempt["id"])["artifact_id"] is None


@pytest.mark.anyio
async def test_delegated_worker_discovers_catalog_and_audits_selected_revision(worker):
    path, work, original, _, _ = worker
    goals = GoalAPI(path)
    grant = work.grant_delegation(original["goal_id"], original["operator_id"])
    run = goals.start_run(delegation_grant_id=grant["id"])
    call = goals.start_tool_call(
        run["id"],
        "delegate_work",
        target_goal_id=original["goal_id"],
        target_revision=1,
    )
    item = work.delegate_work(
        original["goal_id"],
        1,
        "Consider handoff if helpful.",
        WorkspaceInput(source_path=None, base_sha=None),
        "choose-guidance",
        call=call,
    )
    work.create_attempt("delegated-worker", item["id"])
    attempt_grant = work.grant_attempt("delegated-worker", "delegated-credential")
    async with worker_session(work, "delegated-credential") as (session, _, _):
        listed = await session.call_tool("list_skills", {})
        assert not listed.isError, listed.content
        assert [
            (s["id"], s["revision"]) for s in listed.structuredContent["skills"]
        ] == [("handoff", 2)]
        selected = await session.call_tool(
            "read_skill", {"id": "handoff", "revision": 2}
        )
        assert selected.structuredContent == SkillAPI(path).read_skill("handoff", 2)
        # The older owner assignment's revision is outside this worker's scope.
        assert (
            await session.call_tool("read_skill", {"id": "handoff", "revision": 1})
        ).isError
    calls = WorkAPI(path).list_worker_calls("delegated-worker")
    read = next(
        c for c in calls if c["tool"] == "read_skill" and c["outcome"] == "returned"
    )
    assert read["arguments"] == {"id": "handoff", "revision": 2}
    assert read["grant_id"] == attempt_grant["id"]


@pytest.mark.anyio
async def test_operator_run_tool_preserves_delegation_grant(worker):
    path, work, item, _, _ = worker
    goals = GoalAPI(path)
    grant = work.grant_delegation(item["goal_id"], item["operator_id"])
    run = goals.start_run(delegation_grant_id=grant["id"])
    reader = goals.start_run()
    server = create_server(goals, run_id=reader["id"])
    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool("get_run", {"run_id": run["id"]})
    assert not result.isError, result.content
    assert result.structuredContent == goals.get_run(run["id"])
    assert result.structuredContent["delegation_grant_id"] == grant["id"]
