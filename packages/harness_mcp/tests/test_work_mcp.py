import pytest
from mcp.types import CallToolRequest, CallToolRequestParams

from harness_api import GoalAPI, OperatorAPI
from harness_mcp.server import create_server

IMAGE = "example/worker@sha256:" + "a" * 64


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def invoke(server, name, arguments):
    result = await server._mcp_server.request_handlers[CallToolRequest](
        CallToolRequest(params=CallToolRequestParams(name=name, arguments=arguments))
    )
    return result.root


@pytest.mark.anyio
async def test_work_tools_discovery_direct_denials_and_history(tmp_path):
    api = GoalAPI(tmp_path / "db")
    api.work.configure_launcher(
        IMAGE, "http://127.0.0.1:14646", "http://172.17.0.1:14660/mcp"
    )
    goal = api.create_goal("Chess")["id"]
    operator = OperatorAPI(tmp_path / "db").register_operator("Planner")["id"]
    grant = api.grant_work(goal, operator)
    advisory = api.start_run()["id"]
    read_server = create_server(api, run_id=advisory)
    request = {
        "goal_id": goal,
        "expected_revision": 1,
        "brief": "Make cases",
        "skill_revisions": [],
        "retry_key": "one",
    }
    assert "delegate_work" not in {t.name for t in await read_server.list_tools()}
    assert (await invoke(read_server, "delegate_work", request)).isError
    run = api.start_run(work_grant_id=grant["id"])["id"]
    server = create_server(api, run_id=run, work_grant_id=grant["id"])
    assert {"delegate_work", "retry_work"} <= {
        t.name for t in await server.list_tools()
    }
    for fields in [{"image": IMAGE}, {"host_path": "/tmp/auth"}]:
        assert (await invoke(server, "delegate_work", request | fields)).isError
    for selection in [
        {"id": "chess-rules", "revision": True},
        {"id": "chess-rules", "revision": 1, "host_path": "/tmp/auth"},
    ]:
        assert (
            await invoke(
                server, "delegate_work", request | {"skill_revisions": [selection]}
            )
        ).isError
    saved = await invoke(server, "delegate_work", request)
    assert not saved.isError, saved
    (item,) = api.get_goal_activity(goal)["work_items"]
    result = await invoke(read_server, "get_goal_activity", {"goal_id": goal})
    assert not result.isError, result
    assert result.structuredContent["work_items"][0]["id"] == item["id"]
    result = await invoke(read_server, "get_run", {"run_id": run})
    assert not result.isError, result
    assert (
        result.structuredContent["calls"][-1]["work"]["attempt_id"]
        == saved.structuredContent["attempt_id"]
    )
    api.withdraw_work(grant["id"])
    api.grant_work(goal, operator)
    assert "delegate_work" not in {t.name for t in await server.list_tools()}
    assert (await invoke(server, "delegate_work", request)).isError
    assert (
        await invoke(
            server,
            "retry_work",
            {
                "work_item_id": item["id"],
                "expected_latest_attempt_id": item["latest_attempt_id"],
                "retry_key": "again",
            },
        )
    ).isError
    assert len(api.get_goal_activity(goal)["work_items"]) == 1
    assert api.get_run(run)["calls"][-1]["outcome"] == "denied"


def test_worker_http_revocation_and_result_attribution(tmp_path):
    from fastapi.testclient import TestClient

    from harness_api import WorkloadStatus
    from harness_mcp.worker import create_worker_app

    api = GoalAPI(tmp_path / "db")
    api.work.configure_launcher(IMAGE, "http://nomad", "http://worker/mcp")
    goal = api.create_goal("Chess")["id"]
    operator = OperatorAPI(tmp_path / "db").register_operator("Planner")["id"]
    grant = api.grant_work(goal, operator)
    run = api.start_run(work_grant_id=grant["id"])["id"]
    call = api.start_tool_call(
        run, "delegate_work", target_goal_id=goal, target_revision=1
    )
    work = api.work.delegate_work(goal, 1, "Prepare cases", [], "first", call=call)

    class Backend:
        @staticmethod
        def handle(run):
            return "job"

        def start(self, run, spec):
            pass

        def lookup(self, run, spec):
            return WorkloadStatus("running", "job", "original")

    backend = Backend()
    api.work.dispatch(work["attempt_id"], backend)
    app = create_worker_app(
        api, backend, "testserver", 80, lambda token: ("job", token)
    )
    headers = {
        "Host": "testserver:80",
        "Authorization": "Bearer original",
        "Accept": "application/json, text/event-stream",
    }
    with TestClient(app) as client:

        def rpc(method, params):
            response = client.post(
                "/mcp",
                headers=headers,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            )
            assert response.status_code == 200, response.text
            return response.json()["result"]

        assert client.post("/mcp", json={}).status_code == 401
        tools = rpc("tools/list", {})["tools"]
        assert len(tools) == 4
        import jsonschema

        submission = next(t for t in tools if t["name"] == "submit_work_result")
        jsonschema.validate(
            {
                "fixture": {
                    "cases": [
                        {
                            "fen": "position",
                            "move": "e2f2",
                            "expected_legal": False,
                            "reason": "king",
                        }
                    ],
                    "executed": False,
                }
            },
            submission["inputSchema"],
        )
        brief = rpc("tools/call", {"name": "get_work_brief", "arguments": {}})
        assert not brief.get("isError")
        result = rpc(
            "tools/call",
            {
                "name": "submit_work_result",
                "arguments": {
                    "fixture": {
                        "cases": [
                            {
                                "fen": "position",
                                "move": "e2f2",
                                "expected_legal": False,
                                "reason": "king",
                            }
                        ],
                        "executed": False,
                    }
                },
            },
        )
        assert not result.get("isError"), result
        headers["Authorization"] = "Bearer replacement"
        assert rpc("tools/list", {})["tools"] == []
        assert rpc("tools/call", {"name": "get_work_brief", "arguments": {}})["isError"]
        headers["Authorization"] = "Bearer original"
        api.withdraw_work(grant["id"])
        api.grant_work(goal, operator)
        assert rpc("tools/list", {})["tools"] == []
        assert rpc("tools/call", {"name": "get_work_brief", "arguments": {}})["isError"]
    item = api.get_goal_activity(goal)["work_items"][0]
    assert item["attempts"][0]["result"]["evidence_id"] > 0
    assert [c["outcome"] for c in item["attempts"][0]["worker_calls"]][-2:] == [
        "denied",
        "denied",
    ]


def test_nomad_identity_requires_signature_audience_expiry_and_task():
    import time
    from types import SimpleNamespace

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    from harness_mcp.worker import verify_identity

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    keys = SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key())
    )
    claims = {
        "exp": int(time.time()) + 60,
        "aud": "harness-worker",
        "nomad_namespace": "default",
        "nomad_task": "workload",
        "nomad_job_id": "job",
        "nomad_allocation_id": "original",
    }
    token = jwt.encode(claims, key, algorithm="RS256")
    assert verify_identity(token, keys) == ("job", "original")
    for changed in [
        {"aud": "nomadproject.io"},
        {"exp": 1},
        {"nomad_task": "guard"},
        {"nomad_namespace": "other"},
    ]:
        with pytest.raises(jwt.PyJWTError):
            verify_identity(jwt.encode(claims | changed, key, algorithm="RS256"), keys)
    wrong = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(jwt.PyJWTError):
        verify_identity(jwt.encode(claims, wrong, algorithm="RS256"), keys)


@pytest.mark.anyio
async def test_worker_call_yields_while_database_is_locked(tmp_path, monkeypatch):
    import asyncio
    import sqlite3
    from contextlib import closing

    from harness_api import WorkloadStatus
    from harness_mcp.worker import WorkerServer

    path = tmp_path / "db"
    api = GoalAPI(path)
    api.work.configure_launcher(IMAGE, "http://nomad", "http://worker/mcp")
    goal = api.create_goal("Chess")["id"]
    operator = OperatorAPI(path).register_operator("Planner")["id"]
    grant = api.grant_work(goal, operator)
    run = api.start_run(work_grant_id=grant["id"])["id"]
    call = api.start_tool_call(
        run, "delegate_work", target_goal_id=goal, target_revision=1
    )
    work = api.work.delegate_work(goal, 1, "Prepare cases", [], "one", call=call)

    class Backend:
        @staticmethod
        def handle(run_id):
            return "job"

        def start(self, run_id, spec):
            pass

        def lookup(self, run_id, spec):
            return WorkloadStatus("running", "job", "original")

    api.work.dispatch(work["attempt_id"], Backend())
    server = WorkerServer(api.work, "testserver", 80)
    monkeypatch.setattr(server, "binding", lambda: ("job", "original"))
    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        pending = asyncio.create_task(server.call_tool("get_work_brief", {}))
        try:
            await asyncio.sleep(0)
            finished_while_locked = pending.done()
        finally:
            connection.execute("ROLLBACK")
            results = await asyncio.gather(pending, return_exceptions=True)
    assert not finished_while_locked
    assert isinstance(results[0], dict) and results[0]["brief"] == "Prepare cases"
