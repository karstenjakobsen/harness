import shutil
import sqlite3
import subprocess
import sys
from contextlib import asynccontextmanager, closing
from datetime import timedelta
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from harness_api import (
    DATABASE_PATH,
    GoalAPI,
    GoalConflictError,
    GoalValidationError,
    OperatorAPI,
    SkillCatalogError,
    SkillNotFoundError,
    read_skill_catalog,
)
from harness_api.app import create_app
from harness_mcp.server import create_server


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client(tmp_path):
    async with workspace_client(tmp_path) as session:
        yield session


@asynccontextmanager
async def workspace_client(path, *args):
    server = StdioServerParameters(
        command=sys.executable,
        args=["-P", "-m", "harness_mcp.server", *args],
        cwd=path,
    )
    async with (
        stdio_client(server) as (reader, writer),
        ClientSession(reader, writer, timedelta(seconds=5)) as session,
    ):
        await session.initialize()
        yield session


@pytest.mark.anyio
async def test_server_initializes_an_empty_goal_list(client, tmp_path):
    tools = await client.list_tools()
    assert {tool.name for tool in tools.tools} == {
        "list_goals",
        "get_goal_tree",
        "get_goal_progress",
    }
    assert all(tool.annotations.readOnlyHint for tool in tools.tools)
    result = await client.call_tool("list_goals", {})
    assert result.structuredContent == {"goals": []}
    assert (tmp_path / DATABASE_PATH).is_file()
    api = GoalAPI(tmp_path / DATABASE_PATH)
    goal = api.create_goal("Visible goal")
    run = api.start_run()
    assert (
        await client.call_tool("get_goal_activity", {"goal_id": goal["id"]})
    ).isError
    assert (await client.call_tool("get_run", {"run_id": run["id"]})).isError
    assert (await client.call_tool("list_skills", {})).isError
    assert (
        await client.call_tool("read_skill", {"id": "chess-rules", "revision": 1})
    ).isError
    assert api.get_run(run["id"])["calls"] == []


@pytest.mark.anyio
async def test_only_the_bound_session_can_complete_its_subgoal(client, tmp_path):
    path = tmp_path / DATABASE_PATH
    api = GoalAPI(path)
    operator = OperatorAPI(path).register_operator("Reviewer")
    parent = api.create_goal("Parent", status="active")
    child = api.create_goal("Child", status="active", parent_goal_id=parent["id"])
    report = api.record_observation(
        child["id"], confirmation="Verified", retry_key="report"
    )
    first = api.grant_completion(child["id"], operator["id"])
    request = {
        "goal_id": child["id"],
        "expected_revision": child["revision"],
        "evidence_ids": [report["evidence_id"]],
        "rationale": "Owner verified",
    }
    assert (await client.call_tool("complete_goal", request)).isError
    advisory = api.start_run()["id"]
    async with workspace_client(
        tmp_path, "--run-id", str(advisory)
    ) as tracked_advisory:
        assert (await tracked_advisory.call_tool("complete_goal", request)).isError
    (advisory_denial,) = api.get_run(advisory)["calls"]
    assert advisory_denial["outcome"] == "denied"
    assert advisory_denial["target_goal_id"] == child["id"]

    old_run = api.start_run(first["id"])["id"]
    async with workspace_client(
        tmp_path, "--completion-grant", str(first["id"]), "--run-id", str(old_run)
    ) as old:
        tools = await old.list_tools()
        assert {tool.name for tool in tools.tools} >= {"list_skills", "read_skill"}
        (write,) = [tool for tool in tools.tools if not tool.annotations.readOnlyHint]
        assert write.name == "complete_goal"
        assert write.inputSchema["properties"].keys() == request.keys()
        assert write.inputSchema["additionalProperties"] is False
        forged = await old.call_tool("complete_goal", request | {"operator_id": 999})
        assert forged.isError
        api.withdraw_completion(first["id"])
        second = api.grant_completion(child["id"], operator["id"])
        assert all(t.annotations.readOnlyHint for t in (await old.list_tools()).tools)
        assert (await old.call_tool("complete_goal", request)).isError
        assert api.get_goal(child["id"])["status"] == "active"
    for call in api.get_run(old_run)["calls"]:
        assert call["outcome"] == "denied" and call["target_goal_id"] == child["id"]
        assert (
            call["target_revision"] == child["revision"]
            and call["committed_event_id"] is None
        )
        assert call["returned_goals"] is None

    fresh_run = api.start_run(second["id"])["id"]
    async with workspace_client(
        tmp_path, "--completion-grant", str(second["id"]), "--run-id", str(fresh_run)
    ) as fresh:
        result = await fresh.call_tool("complete_goal", request)
        assert not result.isError, result.content
        (history,) = GoalAPI(path).get_goal_history(child["id"])
        assert result.structuredContent == history["completion"]
        assert result.structuredContent["recorded_by_operator_id"] == operator["id"]
        assert history["evidence"] == [report]
        assert api.get_goal(parent["id"]) == parent
        retry = await fresh.call_tool("complete_goal", request)
        assert not retry.isError and retry.structuredContent == result.structuredContent
    commit, retry = api.get_run(fresh_run)["calls"]
    event_id = result.structuredContent["event_id"]
    assert commit["committed_event_id"] == retry["retrieved_event_id"] == event_id
    assert commit["retrieved_event_id"] is None and retry["committed_event_id"] is None
    assert commit["outcome"] == retry["outcome"] == "returned"
    assert commit["returned_goals"] == retry["returned_goals"]


def test_completion_mcp_requires_a_recorded_run(tmp_path):
    path = tmp_path / DATABASE_PATH
    api = GoalAPI(path)
    parent_id = api.create_goal("Parent")["id"]
    child_id = api.create_goal("Child", parent_goal_id=parent_id)["id"]
    operator_id = OperatorAPI(path).register_operator("Reviewer")["id"]
    grant = api.grant_completion(child_id, operator_id)
    with pytest.raises(GoalValidationError, match="recorded run"):
        create_server(api, grant["id"])


@pytest.mark.anyio
async def test_mcp_definition_writes_and_http_attribution(tmp_path):
    path = tmp_path / DATABASE_PATH
    api = GoalAPI(path)
    operator = OperatorAPI(path).register_operator("Planner")
    create_args = {
        "title": "Join the library",
        "retry_key": "library",
        "success_criteria": "Membership is active",
        "measurement_plan": "Ask the owner",
    }
    revise_args = {"goal_id": 1, "expected_revision": 1}
    advisory = api.start_run()["id"]
    async with workspace_client(tmp_path, "--run-id", str(advisory)) as session:
        tools = await session.list_tools()
        assert all(tool.annotations.readOnlyHint for tool in tools.tools)
        assert (await session.call_tool("create_goal", create_args)).isError
        assert (await session.call_tool("revise_goal", revise_args)).isError
    assert all(call["outcome"] == "denied" for call in api.get_run(advisory)["calls"])

    def definition_session(action, **scope):
        grant = api.grant_definition(action, operator["id"], **scope)
        run_id = api.start_run(definition_grant_id=grant["id"])["id"]
        return (
            grant,
            run_id,
            workspace_client(
                tmp_path,
                "--run-id",
                str(run_id),
                "--definition-grant",
                str(grant["id"]),
            ),
        )

    creation_grant, create_run, session = definition_session("create_goal")
    async with session as creator:
        tools = await creator.list_tools()
        (write,) = [tool for tool in tools.tools if not tool.annotations.readOnlyHint]
        assert (
            write.name == "create_goal"
            and write.inputSchema["additionalProperties"] is False
        )
        forbidden = await creator.call_tool(
            "create_goal", create_args | {"parent_goal_id": 2}
        )
        assert forbidden.isError
        created = await creator.call_tool("create_goal", create_args)
        assert not created.isError, created.content
        assert created.structuredContent == {
            "goal_id": 1,
            "revision": 1,
            "status": "draft",
        }
        retry = await creator.call_tool("create_goal", create_args)
        assert retry.structuredContent == created.structuredContent
    goal_id = created.structuredContent["goal_id"]

    revision_grant, revise_run, session = definition_session(
        "revise_goal", goal_id=goal_id
    )
    async with session as reviser:
        tools = await reviser.list_tools()
        (write,) = [tool for tool in tools.tools if not tool.annotations.readOnlyHint]
        assert (
            write.name == "revise_goal"
            and write.inputSchema["additionalProperties"] is False
        )
        assert (await reviser.call_tool("create_goal", create_args)).isError
        patch = revise_args | {
            "success_criteria": "Active membership and first checkout"
        }
        assert (await reviser.call_tool("revise_goal", patch | {"grant_id": 1})).isError
        revised = await reviser.call_tool("revise_goal", patch)
        assert not revised.isError, revised.content
        assert revised.structuredContent == {
            "goal_id": goal_id,
            "revision": 2,
            "status": "draft",
        }
        assert (await reviser.call_tool("revise_goal", patch)).isError
        no_op = await reviser.call_tool(
            "revise_goal", {"goal_id": goal_id, "expected_revision": 2}
        )
        assert no_op.structuredContent == revised.structuredContent

    # Commit another revision and reopen the API before the tool result is recorded.
    interrupted = api.start_tool_call(
        revise_run, "revise_goal", target_goal_id=goal_id, target_revision=2
    )
    api.revise_delegated_goal(goal_id, 2, call=interrupted, measurement_plan=None)

    with TestClient(create_app(path)) as client:

        def get(url):
            return client.get(url).raise_for_status().json()

        timeline = get(f"/goals/{goal_id}/history?view=activity")["timeline"]
        revision_entries = [entry for entry in timeline if entry["kind"] == "revision"]
        assert [entry["definition"]["revision"] for entry in revision_entries] == [
            1,
            2,
            3,
        ]
        assert [
            entry["definition"]["measurement_plan"] for entry in revision_entries
        ] == ["Ask the owner", "Ask the owner", None]
        for revision, entry, grant, result in zip(
            [1, 2, 3],
            revision_entries,
            [creation_grant, revision_grant, revision_grant],
            [created.structuredContent, revised.structuredContent, None],
            strict=True,
        ):
            link = entry["committing_call"]
            run = get(f"/runs/{link['run_id']}")
            assert (
                run["operator_id"] == operator["id"]
                and run["definition_grant"] == grant
            )
            (call,) = [
                call for call in run["calls"] if call["sequence"] == link["sequence"]
            ]
            assert call["tool"] == grant["action"]
            assert call["committed_revision"] == {
                "goal_id": goal_id,
                "revision": revision,
            }
            if result is None:
                assert (
                    call["outcome"] == "unfinished" and call["returned_goals"] is None
                )
            else:
                assert call["outcome"] == "returned"
                assert call["returned_goals"] == [
                    result | {"observation_ids": [], "decision": None}
                ]

        assert all(entry.get("run_id") != advisory for entry in timeline)
        denied = [entry for entry in timeline if entry.get("outcome") == "denied"]
        assert len(denied) == 2 and all(
            entry["relationship"] == "revision_target" for entry in denied
        )
        assert get(f"/runs/{create_run}")["calls"][-1]["retrieved_revision"] == {
            "goal_id": goal_id,
            "revision": 1,
        }
        no_op_record = get(f"/runs/{revise_run}")["calls"][-2]
        assert (
            no_op_record["outcome"] == "returned"
            and no_op_record["committed_revision"] is None
        )
        assert all(
            "committing_call" not in entry for entry in get(f"/goals/{goal_id}/history")
        )
        goal = get(f"/goals/{goal_id}")
        assert goal["status"] == "draft" and goal["completion"] is None


@pytest.mark.anyio
async def test_tree_includes_grandchild_and_owner_supplied_evidence(client, tmp_path):
    api = GoalAPI(tmp_path / DATABASE_PATH)
    root = api.create_goal("Root")
    child = api.create_goal("Child", parent_goal_id=root["id"])
    leaf = api.create_goal("Grandchild", parent_goal_id=child["id"])
    api.create_goal("Unrelated")
    decision = api.complete_goal(leaf["id"], 1, reference="app:receipt/7")
    invalid = await client.call_tool("get_goal_tree", {"goal_id": True})
    assert invalid.isError
    result = await client.call_tool("get_goal_tree", {"goal_id": root["id"]})
    assert not result.isError
    assert result.structuredContent == {
        "root_id": root["id"],
        "goals": [root, child, {**leaf, "status": "completed", "completion": decision}],
    }
    with pytest.raises(GoalConflictError):
        api.delete_goal(child["id"])
    after = await client.call_tool("get_goal_tree", {"goal_id": root["id"]})
    assert not after.isError
    assert after.structuredContent == result.structuredContent


@pytest.mark.anyio
async def test_lists_latest_revisions_and_current_assignments_for_admin(
    client, tmp_path
):
    with closing(sqlite3.connect(tmp_path / DATABASE_PATH)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript("""
            INSERT INTO users (username, display_name) VALUES ('other', 'Other user');
            INSERT INTO operators (id, owner_user_id, name)
                VALUES (1, 1, 'Alice'), (2, 1, 'Bob');
            INSERT INTO goals (id, owner_user_id, status)
                VALUES (1, 1, 'active'), (2, 1, 'draft'), (3, 2, 'active');
            INSERT INTO goal_revisions (goal_id, revision, title)
                VALUES (1, 1, 'First title'), (1, 2, 'Current title');
            INSERT INTO goal_assignments (goal_id, operator_id, released_at)
                VALUES (1, 1, CURRENT_TIMESTAMP), (1, 2, NULL);
            """)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO goal_assignments (goal_id, operator_id) VALUES (1, 1)"
            )

    active = {
        "id": 1,
        "status": "active",
        "title": "Current title",
        "revision": 2,
        "operator": "Bob",
    }
    draft = {
        "id": 2,
        "status": "draft",
        "title": None,
        "revision": None,
        "operator": None,
    }

    all_goals = await client.call_tool("list_goals", {})
    assert all_goals.structuredContent == {"goals": [active, draft]}
    active_goals = await client.call_tool("list_goals", {"status": "active"})
    assert active_goals.structuredContent == {"goals": [active]}


@pytest.mark.anyio
async def test_progress_returns_selected_model_assessment(client, tmp_path):
    api = GoalAPI(tmp_path / DATABASE_PATH)
    goal = api.create_goal("Food log", status="active", target_distinct_dates=7)
    goal_id = goal["id"]
    report = GoalAPI(tmp_path / DATABASE_PATH, local_owner=False).record_observation(
        goal_id,
        confirmation="Meals logged",
        reported_date="2026-11-23",
        retry_key="first",
    )
    api.update_goal(goal_id, target_distinct_dates=14)
    for args in ({}, {"revision": 1}):
        result = await client.call_tool(
            "get_goal_progress", {"goal_id": goal_id, **args}
        )
        assert not result.isError
        assert result.structuredContent == api.get_goal_progress(goal_id, **args)
        assert result.structuredContent["evidence"] == [report]
        assert result.structuredContent["days"] == []
    invalid = await client.call_tool(
        "get_goal_progress", {"goal_id": goal_id, "revision": True}
    )
    assert invalid.isError


@pytest.mark.anyio
async def test_history_reads_keep_the_state_seen_by_another_operator(tmp_path):
    path = tmp_path / DATABASE_PATH
    api = GoalAPI(path)
    operators = OperatorAPI(path)
    author = operators.register_operator("Author")
    reviewer = operators.register_operator("Reviewer")
    goal_id = api.create_goal("Library", success_criteria="Membership is active")["id"]
    other = api.create_goal("Other subgoal", parent_goal_id=goal_id)["id"]
    report = api.record_observation(
        goal_id, confirmation="Verified", retry_key="report"
    )
    revision_grant = api.grant_definition("revise_goal", author["id"], goal_id=goal_id)
    completion_grant = api.grant_completion(other, reviewer["id"])
    author_run = api.start_run(definition_grant_id=revision_grant["id"])["id"]
    committing_call = api.start_tool_call(
        author_run, "revise_goal", target_goal_id=goal_id, target_revision=1
    )
    revised = api.revise_delegated_goal(
        goal_id,
        1,
        call=committing_call,
        success_criteria="Membership and first checkout",
    )
    reader_run = api.start_run(completion_grant["id"])["id"]
    activity_url = f"/goals/{goal_id}/history?view=activity"

    def get(url):
        return http.get(url).raise_for_status().json()

    with TestClient(create_app(path)) as http:
        activity = get(activity_url)
        author_snapshot = get(f"/runs/{author_run}")
        assert author_snapshot["outcome"] == "unfinished"
        (before,) = author_snapshot["calls"]
        assert before["outcome"] == "unfinished" and before["returned_goals"] is None
        assert before["committed_revision"] == {"goal_id": goal_id, "revision": 2}

        async with workspace_client(
            tmp_path,
            "--run-id",
            str(reader_run),
            "--completion-grant",
            str(completion_grant["id"]),
        ) as session:
            tools = await session.list_tools()
            assert {
                tool.name for tool in tools.tools if tool.annotations.readOnlyHint
            } >= {"get_goal_activity", "get_run"}
            result = await session.call_tool("get_run", {"run_id": reader_run})
            assert result.structuredContent["calls"] == []
            result = await session.call_tool("get_goal_activity", {"goal_id": goal_id})
            assert result.structuredContent == activity
            result = await session.call_tool("get_run", {"run_id": author_run})
            assert result.structuredContent == author_snapshot
            result = await session.call_tool(
                "revise_goal",
                {"goal_id": goal_id, "expected_revision": 2, "title": "Denied"},
            )
            assert result.isError

        api.finish_run(reader_run, "succeeded")
        api.finish_tool_call(
            committing_call,
            "returned",
            returned_goals=[revised | {"observation_ids": [], "decision": None}],
        )
        api.finish_run(author_run, "succeeded")
        timeline = get(activity_url)["timeline"]
        revision = next(
            item
            for item in timeline
            if item["kind"] == "revision" and item["definition"]["revision"] == 2
        )
        assert revision["committing_call"] == committing_call
        author_record = get(f"/runs/{revision['committing_call']['run_id']}")
        assert author_record["operator_id"] == author["id"]
        assert author_record["outcome"] == "succeeded"
        (after,) = author_record["calls"]
        assert after["outcome"] == "returned"
        assert after["committed_revision"] == before["committed_revision"]

        (activity_entry,) = [
            item for item in timeline if item.get("tool") == "get_goal_activity"
        ]
        reader_record = get(f"/runs/{activity_entry['run_id']}")
        assert reader_record["operator_id"] == reviewer["id"]
        self_read, activity_read, run_read, denial = reader_record["calls"]
        assert self_read["returned_history"] == {
            "run_id": reader_run,
            "outcome": "unfinished",
            "calls": [],
        }
        assert activity_read["sequence"] == activity_entry["sequence"]
        assert activity_read["target_goal_id"] == goal_id
        assert activity_read["returned_history"] == {
            "goal_id": goal_id,
            "timeline": [
                {"kind": "revision", "revision": 1, "committing_call": None},
                {"kind": "observation", "evidence_id": report["evidence_id"]},
                next(item for item in activity["timeline"] if item["kind"] == "call"),
                {"kind": "revision", "revision": 2, "committing_call": committing_call},
            ],
        }
        assert run_read["target_run_id"] == author_run
        assert run_read["returned_history"] == {
            "run_id": author_run,
            "outcome": "unfinished",
            "calls": [
                committing_call
                | {
                    "outcome": "unfinished",
                    "committed_revision": {"goal_id": goal_id, "revision": 2},
                    "retrieved_revision": None,
                    "committed_event_id": None,
                    "retrieved_event_id": None,
                }
            ],
        }
        assert denial["outcome"] == "denied" and denial["committed_revision"] is None
        assert api.get_goal(goal_id)["revision"] == 2
        assert api.get_goal(other)["completion"] is None

        audit_run = api.start_run()["id"]
        async with workspace_client(tmp_path, "--run-id", str(audit_run)) as session:
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} >= {
                "get_goal_activity",
                "get_run",
            }
            result = await session.call_tool("get_run", {"run_id": reader_run})
            assert result.structuredContent == reader_record
            result = await session.call_tool("get_run", {"run_id": author_run})
            assert result.structuredContent == author_record
        inspection, latest = get(f"/runs/{audit_run}")["calls"]
        saved_calls = inspection["returned_history"]["calls"]
        assert [call["sequence"] for call in saved_calls] == [1, 2, 3, 4]
        assert all("returned_history" not in call for call in saved_calls)
        assert latest["returned_history"]["outcome"] == "succeeded"
        assert latest["returned_history"]["calls"][0]["outcome"] == "returned"
        saved_call = run_read["returned_history"]["calls"][0]
        print(
            f"\nMCP snapshot verified over HTTP. Run {author_run}, "
            f"call {after['sequence']} now shows {after['outcome']}."
        )
        print(
            f"B's earlier read in run {reader_run}, call {run_read['sequence']} "
            f"still shows A's run and call as {run_read['returned_history']['outcome']} "
            f"and {saved_call['outcome']} with revision "
            f"{saved_call['committed_revision']['revision']} committed."
        )
        print(
            f"B's direct revise_goal in call {denial['sequence']} was "
            f"{denial['outcome']}. The library goal remained at revision 2."
        )


@pytest.mark.anyio
async def test_history_reads_audit_foreign_targets_without_exposing_records(tmp_path):
    path = tmp_path / DATABASE_PATH
    api = GoalAPI(path)
    reader_run = api.start_run()["id"]
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.executescript("""
            INSERT INTO users (id, username, display_name) VALUES (2, 'other', 'Other');
            INSERT INTO goals (id, owner_user_id) VALUES (2, 2);
            INSERT INTO operator_runs (id, owner_user_id, started_at)
            VALUES (2, 2, '2025-01-01 10:00:00');
        """)
    async with workspace_client(tmp_path, "--run-id", str(reader_run)) as session:
        for tool, target in (("get_goal_activity", "goal_id"), ("get_run", "run_id")):
            result = await session.call_tool(tool, {target: 2})
            assert result.isError and result.structuredContent is None
        result = await session.call_tool("get_run", {"run_id": 999})
        assert result.isError and result.structuredContent is None
    goal_read, run_read, missing_run_read = api.get_run(reader_run)["calls"]
    assert goal_read["target_goal_id"] == 2 and goal_read["target_run_id"] is None
    assert run_read["target_run_id"] == 2 and run_read["target_goal_id"] is None
    assert missing_run_read["target_run_id"] == 999
    assert all(
        call["outcome"] == "denied" and call["returned_history"] is None
        for call in (goal_read, run_read, missing_run_read)
    )


@pytest.mark.anyio
async def test_audit_keeps_actual_result_relationships_after_revision(tmp_path):
    path = tmp_path / DATABASE_PATH
    api = GoalAPI(path)
    root = api.create_goal("Parent with private title", status="active")["id"]
    child = api.create_goal("Child", status="active", parent_goal_id=root)["id"]
    report = api.record_observation(
        child, confirmation="Private report", retry_key="report"
    )
    evidence = report["evidence_id"]
    decision = api.complete_goal(
        child, 1, reference="Private receipt", evidence_ids=[evidence]
    )
    run_id = api.start_run()["id"]
    async with workspace_client(tmp_path, "--run-id", str(run_id)) as session:
        for tool, arguments in (
            ("list_goals", {}),
            ("get_goal_tree", {"goal_id": root}),
            ("get_goal_progress", {"goal_id": child, "revision": 1}),
            ("list_goals", {"status": "active"}),
            ("list_goals", {"status": "paused"}),
        ):
            result = await session.call_tool(tool, arguments)
            assert not result.isError, result.content
        invalid = await session.call_tool(
            "get_goal_progress", {"goal_id": child, "revision": "Private invalid arg"}
        )
        assert invalid.isError
    api.finish_run(run_id, "succeeded")
    saved = api.get_run(run_id)
    api.update_goal(child, title="Updated child")
    api.record_observation(child, confirmation="Later report", retry_key="later")
    api = GoalAPI(path)
    assert api.get_run(run_id) == saved
    listed, tree, progress, filtered, empty, denied = saved["calls"]
    assert listed["target_goal_id"] is None
    assert listed["returned_goals"] is not None
    assert [goal["goal_id"] for goal in listed["returned_goals"]] == [root, child]
    assert tree["target_goal_id"] == root
    assert tree["returned_goals"] is not None
    child_result = tree["returned_goals"][1]
    assert child_result == {
        "goal_id": child,
        "revision": 1,
        "status": "completed",
        "observation_ids": [],
        "decision": {
            "event_id": decision["event_id"],
            "evidence_ids": [evidence],
            "statement_evidence_id": decision["statement_evidence_id"],
        },
    }
    assert progress["target_goal_id"] == child and progress["target_revision"] == 1
    assert progress["returned_goals"] == [
        {
            **child_result,
            "decision": None,
            "observation_ids": [evidence, decision["statement_evidence_id"]],
        }
    ]
    assert filtered["returned_goals"] is not None
    assert [goal["goal_id"] for goal in filtered["returned_goals"]] == [root]
    assert empty["outcome"] == "returned" and empty["returned_goals"] == []
    assert denied["outcome"] == "denied" and denied["returned_goals"] is None
    assert denied["target_goal_id"] == child and denied["target_revision"] is None
    calls = [
        entry
        for entry in api.get_goal_activity(child)["timeline"]
        if entry["kind"] == "call"
    ]
    assert [call["at"] for call in calls] == sorted(call["at"] for call in calls)
    assert sorted((call["sequence"], call["relationship"]) for call in calls) == [
        (1, "listed"),
        (2, "descendant"),
        (3, "requested"),
        (6, "requested"),
    ]
    with closing(sqlite3.connect(path)) as db:
        audit_data = "\n".join(
            line
            for line in db.iterdump()
            if line.startswith(('INSERT INTO "operator_runs"', 'INSERT INTO "run_call'))
        )
    assert 'INSERT INTO "run_call_goals"' in audit_data
    assert "Private" not in audit_data


@pytest.mark.anyio
async def test_http_discovers_both_mcp_reviews_and_resolves_the_decision(tmp_path):
    path = tmp_path / DATABASE_PATH
    api = GoalAPI(path)
    parent = api.create_goal("Exercise routine", status="active")["id"]
    goal = api.create_goal("Gym membership", parent_goal_id=parent, status="active")
    goal_id = goal["id"]
    operator_id = OperatorAPI(path).register_operator("Reviewer")["id"]
    grant_id = api.grant_completion(goal_id, operator_id)["id"]
    tour = api.record_observation(
        goal_id, confirmation="I took the tour", retry_key="tour"
    )
    receipt = api.record_observation(
        goal_id, reference="receipt:day-pass", retry_key="receipt"
    )
    first_ids = [tour["evidence_id"], receipt["evidence_id"]]

    async def review(confirmation=None):
        run_id = api.start_run(grant_id)["id"]
        async with workspace_client(
            tmp_path, "--run-id", str(run_id), "--completion-grant", str(grant_id)
        ) as session:
            progress = await session.call_tool(
                "get_goal_progress", {"goal_id": goal_id}
            )
            assert not progress.isError
            if confirmation is not None:
                result = await session.call_tool(
                    "complete_goal",
                    {
                        "goal_id": goal_id,
                        "expected_revision": goal["revision"],
                        "evidence_ids": [confirmation["evidence_id"]],
                        "rationale": "The owner confirmed active membership.",
                    },
                )
                assert not result.isError
        api.finish_run(run_id, "succeeded")

    await review()
    confirmation = api.record_observation(
        goal_id, confirmation="My membership is active", retry_key="membership"
    )
    await review(confirmation)

    with TestClient(create_app(path)) as client:

        def get(url):
            response = client.get(url)
            response.raise_for_status()
            return response.json()

        history = get(f"/goals/{goal_id}/history?view=activity")["timeline"]
        ids = {entry["run_id"] for entry in history if entry["kind"] == "call"}
        first, second = sorted(
            (get(f"/runs/{run_id}") for run_id in ids),
            key=lambda run: run["started_at"],
        )
        (early_read,) = first["calls"]
        later_read, commit = second["calls"]
        assert early_read["tool"] == later_read["tool"] == "get_goal_progress"
        assert early_read["returned_goals"][0]["observation_ids"] == first_ids
        assert later_read["returned_goals"][0]["observation_ids"] == [
            *first_ids,
            confirmation["evidence_id"],
        ]
        (entry,) = [entry for entry in history if entry["kind"] == "decision"]
        decision = entry["decision"]
        assert commit["committed_event_id"] == decision["event_id"]
        assert entry["committing_call"] == {
            "run_id": second["id"],
            "sequence": commit["sequence"],
        }
        assert decision["revision"] == goal["revision"]
        assert (
            decision["recorded_by_operator_id"] == second["operator_id"] == operator_id
        )
        assert (
            decision["completion_grant_id"] == second["completion_grant_id"] == grant_id
        )
        assert decision["rationale"] == "The owner confirmed active membership."
        assert [
            entry["observation"]
            for entry in history
            if entry["kind"] == "observation"
            and entry["observation"]["evidence_id"] in decision["evidence_ids"]
        ] == [confirmation]
        assert confirmation["submitted_by"] == 1 and confirmation["recorded_at"]
        assert get(f"/runs/{first['id']}") == first
        assert get(f"/goals/{goal_id}")["status"] == "completed"
        assert get(f"/goals/{parent}")["status"] == "active"


@pytest.mark.anyio
async def test_catalog_import_and_historical_skill_reads(tmp_path, monkeypatch):
    repo = tmp_path / "source"
    workspace = tmp_path / "workspace"
    repo.mkdir()
    workspace.mkdir()
    # Import Go first so the conflicting chess revision exercises rollback of a valid insert.
    go = repo / "skills/a-go"
    chess = repo / "skills/b-chess"
    for folder, skill_id in ((go, "go-testing"), (chess, "chess-rules")):
        folder.mkdir(parents=True)
        (folder / "operator.yaml").write_text(
            f"kind: skill\nid: {skill_id}\nrevision: 1\nname: {skill_id}\ndescription: Example\nauthor: Test\n"
        )
        (folder / "SKILL.md").write_text(f"Instructions for {skill_id}\n")

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
        ).stdout.strip()

    def commit(message):
        git("add", "-A")
        git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.org",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            message,
        )
        return git("rev-parse", "HEAD")

    git("init", "-q")
    original_sha = commit("Two skills")
    api = GoalAPI(workspace / DATABASE_PATH)

    def load():
        api.skills.import_catalog(read_skill_catalog(repo))

    manifest = (chess / "operator.yaml").read_bytes()
    markdown = (chess / "SKILL.md").read_bytes()
    original_hash = sha256(
        len(manifest).to_bytes(8, "big") + manifest + markdown
    ).hexdigest()
    load()
    load()
    (repo / "README").write_text("Unrelated commit")
    commit("Unrelated")
    (chess / "SKILL.md").write_text("Uncommitted edit")
    load()
    ref = {"id": "chess-rules", "revision": 1}
    go_ref = {"id": "go-testing", "revision": 1}
    run_id = api.start_run()["id"]
    async with workspace_client(workspace, "--run-id", str(run_id)) as session:
        listed = (await session.call_tool("list_skills", {})).structuredContent[
            "skills"
        ]
        assert [item.keys() for item in listed] == [
            set(ref) | {"name", "description"}
        ] * 2
        assert [(item["id"], item["revision"]) for item in listed] == [
            ("chess-rules", 1),
            ("go-testing", 1),
        ]
        original = (await session.call_tool("read_skill", ref)).structuredContent
        assert (
            original["instructions"].encode() == markdown
            and original["manifest"].encode() == manifest
        )
        assert (
            original["source_path"],
            original["commit_sha"],
            original["content_hash"],
        ) == ("skills/b-chess", original_sha, original_hash)
        assert (
            await session.call_tool("read_skill", {"id": "go-testing", "revision": 2})
        ).isError
        malformed = await session.call_tool(
            "read_skill", {"id": "not a skill ID", "revision": 1}
        )
        assert malformed.isError
    # A requested full read interrupted before returning has no returned reference.
    api.start_tool_call(
        run_id, "read_skill", target_skill_id="go-testing", target_revision=1
    )
    api.finish_run(run_id, "succeeded")
    listing, reading, failed, malformed, interrupted = api.get_run(run_id)["calls"]
    assert malformed["outcome"] == "denied" and malformed["target_skill_id"] is None
    assert (
        listing["returned_skills"] == [ref, go_ref]
        and listing["returned_goals"] is None
    )
    assert (
        reading["returned_skills"] == [ref] and reading["target_skill_id"] == ref["id"]
    )
    assert failed["outcome"] == "denied" and failed["returned_skills"] is None
    assert (
        interrupted["outcome"] == "unfinished"
        and interrupted["returned_skills"] is None
    )

    go_manifest = go / "operator.yaml"
    go_manifest.write_text(
        go_manifest.read_text().replace("revision: 1", "revision: 2")
    )
    commit("Go revision 2 and conflicting chess text")
    url = "/skills/chess-rules/revisions/1"
    with pytest.raises(
        SkillCatalogError, match="chess-rules.*revision 1.*Bump"
    ) as conflict:
        load()
    after_conflict = api.skills.list_skills()
    assert after_conflict == listed
    with pytest.raises(SkillNotFoundError):
        api.skills.read_skill("go-testing", 2)
    print(f"\nOffline catalog import rejected: {conflict.value}")
    print(
        "Discovery after rollback:", [(s["id"], s["revision"]) for s in after_conflict]
    )
    print("Exact lookup of go-testing revision 2 raised SkillNotFoundError.")
    with TestClient(create_app(workspace / DATABASE_PATH)) as http:
        past = http.get(f"/runs/{run_id}").raise_for_status().json()["calls"][1]
        (item,) = past["returned_skills"]
        assert (
            http.get(f"/skills/{item['id']}/revisions/{item['revision']}")
            .raise_for_status()
            .json()
            == original
        )

    (chess / "SKILL.md").write_bytes(markdown)
    (chess / "operator.yaml").write_bytes(manifest + b"# new description pending\n")
    commit("Conflicting manifest only")
    with pytest.raises(SkillCatalogError, match="chess-rules.*revision 1.*Bump"):
        load()
    assert api.skills.list_skills() == listed
    (chess / "operator.yaml").write_bytes(
        manifest.replace(b"revision: 1", b"revision: 2")
    )
    (chess / "SKILL.md").write_text("Chess revision two\n")
    (chess.parent / "b-chess").rename(chess.parent / "moved-chess")
    commit("Bump chess revision and move its folder")
    load()
    assert [(item["id"], item["revision"]) for item in api.skills.list_skills()] == [
        ("chess-rules", 2),
        ("go-testing", 2),
    ]
    assert (
        api.skills.read_skill("chess-rules", 2)["source_path"] == "skills/moved-chess"
    )

    shutil.rmtree(chess.parent / "moved-chess")
    commit("Remove chess from discovery")
    load()
    repo.rename(tmp_path / "checkout-unavailable")
    async with workspace_client(
        workspace, "--run-id", str(api.start_run()["id"])
    ) as session:
        assert (await session.call_tool("list_skills", {})).structuredContent == {
            "skills": [listed[1] | {"revision": 2}]
        }
        assert (
            await session.call_tool("read_skill", ref)
        ).structuredContent == original
    # Opening the HTTP service and following saved reads also work without a Git executable.
    monkeypatch.setenv("PATH", str(workspace))
    with TestClient(create_app(workspace / DATABASE_PATH)) as http:
        historical = http.get(url).raise_for_status().json()
        assert historical == original
        current = http.get("/skills").raise_for_status().json()
        assert current == [listed[1] | {"revision": 2}]
        assert http.get("/skills/chess-rules/revisions/3").status_code == 404
        assert http.get("/skills/chess-rules/revisions/3/reads").status_code == 404
        readers = http.get(url + "/reads").raise_for_status().json()
        assert readers == [
            {"run_id": run_id, "sequence": reading["sequence"]},
            {"run_id": run_id + 1, "sequence": 2},
        ]
        go_reads = (
            http.get("/skills/go-testing/revisions/1/reads").raise_for_status().json()
        )
        assert go_reads == []
    print("Discovery after removal:", [(s["id"], s["revision"]) for s in current])
    print(f"Historical HTTP read without Git: {url}")
    print(f"  Instructions: {historical['instructions'].rstrip()}")
    print(f"  Source: {historical['source_path']} at {historical['commit_sha']}")
    print(f"  Content hash: {historical['content_hash']}")
    print(f"  Full reads of chess-rules revision 1: {readers}")
    print(f"  Full reads of go-testing revision 1 (only listed): {go_reads}")


@pytest.mark.anyio
async def test_subgoal_tool_is_parent_scoped_and_audits_request_and_result(tmp_path):
    path = tmp_path / DATABASE_PATH
    api = GoalAPI(path)
    operator = OperatorAPI(path).register_operator("Planner")
    parent = api.create_goal("Join a club")["id"]
    other = api.create_goal("Renew membership")["id"]
    request = {
        "parent_goal_id": parent,
        "expected_parent_revision": 1,
        "title": "Attend a meeting",
        "retry_key": "meeting",
        "success_criteria": "Owner confirms attendance",
        "duration_days": 14,
    }
    top_level = api.grant_definition("create_goal", operator["id"])
    grant = api.grant_definition("create_subgoal", operator["id"], goal_id=parent)
    for bound in (None, top_level):
        run = api.start_run(definition_grant_id=bound["id"] if bound else None)["id"]
        args = ["--definition-grant", str(bound["id"])] if bound else []
        async with workspace_client(tmp_path, "--run-id", str(run), *args) as session:
            assert "create_subgoal" not in {
                tool.name for tool in (await session.list_tools()).tools
            }
            assert (await session.call_tool("create_subgoal", request)).isError
        (denied,) = api.get_run(run)["calls"]
        assert (
            denied["outcome"],
            denied["target_goal_id"],
            denied["target_revision"],
        ) == ("denied", parent, 1)
        assert denied["committed_revision"] is None and denied["returned_goals"] is None
    run = api.start_run(definition_grant_id=grant["id"])["id"]
    async with workspace_client(
        tmp_path, "--run-id", str(run), "--definition-grant", str(grant["id"])
    ) as session:
        tools = (await session.list_tools()).tools
        assert [t.name for t in tools if not t.annotations.readOnlyHint] == [
            "create_subgoal"
        ]
        assert (
            await session.call_tool(
                "revise_goal",
                {"goal_id": parent, "expected_revision": 1, "title": "Different"},
            )
        ).isError
        result = await session.call_tool("create_subgoal", request)
        assert not result.isError
        child = result.structuredContent["goal_id"]
        assert result.structuredContent == {
            "goal_id": child,
            "revision": 1,
            "status": "draft",
        }
        assert api.get_goal(child)["duration_days"] == 14
        assert api.get_goal(child)["success_criteria"] == request["success_criteria"]
        for target in (other, child):
            assert (
                await session.call_tool(
                    "create_subgoal", request | {"parent_goal_id": target}
                )
            ).isError
        assert (
            await session.call_tool("create_subgoal", request | {"status": "active"})
        ).isError
        assert (
            await session.call_tool("create_subgoal", request)
        ).structuredContent == result.structuredContent
    revision_denial, creation, wrong_parent, grandchild, invalid, retry = api.get_run(
        run
    )["calls"]
    assert revision_denial["outcome"] == "denied"
    assert (creation["target_goal_id"], creation["target_revision"]) == (parent, 1)
    assert (
        creation["committed_revision"]
        == retry["retrieved_revision"]
        == {"goal_id": child, "revision": 1}
    )
    assert (
        creation["returned_goals"]
        == retry["returned_goals"]
        == [result.structuredContent | {"observation_ids": [], "decision": None}]
    )
    for denial, target in [
        (wrong_parent, other),
        (grandchild, child),
        (invalid, parent),
    ]:
        assert (
            denial["outcome"],
            denial["target_goal_id"],
            denial["target_revision"],
        ) == ("denied", target, 1)
        assert (
            denial["committed_revision"] is None
            and denial["retrieved_revision"] is None
        )
    assert [g["id"] for g in api.list_goals()] == [parent, other, child]
    child_activity = api.get_goal_activity(child)["timeline"]
    assert {
        e["sequence"]: e["relationship"] for e in child_activity if e["kind"] == "call"
    } == {
        creation["sequence"]: "creation_result",
        grandchild["sequence"]: "requested",
        retry["sequence"]: "creation_result",
    }


@pytest.mark.anyio
async def test_subgoal_discovery_tracks_withdrawal_and_regrant(tmp_path):
    path = tmp_path / DATABASE_PATH
    api = GoalAPI(path)
    operator = OperatorAPI(path).register_operator("Planner")
    parent = api.create_goal("Join a club")["id"]
    grant = api.grant_definition("create_subgoal", operator["id"], goal_id=parent)
    run = api.start_run(definition_grant_id=grant["id"])["id"]
    async with workspace_client(
        tmp_path, "--run-id", str(run), "--definition-grant", str(grant["id"])
    ) as session:

        async def writes():
            return [
                t.name
                for t in (await session.list_tools()).tools
                if not t.annotations.readOnlyHint
            ]

        assert await writes() == ["create_subgoal"]
        api.withdraw_definition_grant(grant["id"])
        assert await writes() == []
        replacement = api.grant_definition(
            "create_subgoal", operator["id"], goal_id=parent
        )
        assert await writes() == []
        request = {
            "parent_goal_id": parent,
            "expected_parent_revision": 1,
            "title": "Attend a meeting",
            "success_criteria": "The owner attended.",
            "retry_key": "first",
        }
        assert (await session.call_tool("create_subgoal", request)).isError
        assert not (
            await session.call_tool("get_goal_tree", {"goal_id": parent})
        ).isError
    denied, read = api.get_run(run)["calls"]
    assert (denied["outcome"], denied["target_goal_id"], denied["target_revision"]) == (
        "denied",
        parent,
        1,
    )
    assert denied["committed_revision"] is None and read["outcome"] == "returned"
    assert len(api.list_goals()) == 1
    fresh = api.start_run(definition_grant_id=replacement["id"])["id"]
    async with workspace_client(
        tmp_path, "--run-id", str(fresh), "--definition-grant", str(replacement["id"])
    ) as session:
        result = await session.call_tool("create_subgoal", request)
        assert result.structuredContent["status"] == "draft"
        api.finish_run(fresh, "succeeded")
        assert all(
            t.annotations.readOnlyHint for t in (await session.list_tools()).tools
        )
        rejected = await session.call_tool("create_subgoal", request)
        assert rejected.isError and "finished" in rejected.content[0].text
    assert len(api.get_run(fresh)["calls"]) == 1
