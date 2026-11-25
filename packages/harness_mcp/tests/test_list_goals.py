import sqlite3
import sys
from contextlib import closing
from datetime import timedelta

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from harness_api import DATABASE_PATH, GoalAPI, GoalConflictError


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client(tmp_path):
    server = StdioServerParameters(
        command=sys.executable,
        args=["-P", "-m", "harness_mcp.server"],
        cwd=tmp_path,
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
