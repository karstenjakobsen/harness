import sqlite3
import sys
from contextlib import closing
from datetime import timedelta

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from harness_api import DATABASE_PATH


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
    assert [tool.name for tool in tools.tools] == ["list_goals"]
    result = await client.call_tool("list_goals", {})
    assert result.structuredContent == {"goals": []}
    assert (tmp_path / DATABASE_PATH).is_file()


@pytest.mark.anyio
async def test_lists_latest_revisions_and_current_assignments_for_local_user(
    client, tmp_path
):
    with closing(sqlite3.connect(tmp_path / DATABASE_PATH)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript("""
            INSERT INTO users (id, display_name) VALUES ('other', 'Other user');
            INSERT INTO operators (id, owner_user_id, name)
                VALUES (1, 'local', 'Alice'), (2, 'local', 'Bob');
            INSERT INTO goals (id, owner_user_id, status)
                VALUES (1, 'local', 'active'), (2, 'local', 'draft'), (3, 'other', 'active');
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
