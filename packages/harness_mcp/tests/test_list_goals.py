import sqlite3
import sys
from contextlib import asynccontextmanager, closing
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from harness_api import DATABASE_PATH, GoalAPI, GoalConflictError, OperatorAPI
from harness_api.app import create_app


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
        (write,) = [tool for tool in tools.tools if not tool.annotations.readOnlyHint]
        assert write.name == "complete_goal"
        assert write.inputSchema["properties"].keys() == request.keys()
        assert write.inputSchema["additionalProperties"] is False
        forged = await old.call_tool("complete_goal", request | {"operator_id": 999})
        assert forged.isError
        api.withdraw_completion(first["id"])
        second = api.grant_completion(child["id"], operator["id"])
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
    assert [(call["sequence"], call["relationship"]) for call in calls] == [
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
