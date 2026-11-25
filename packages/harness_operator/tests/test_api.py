import json
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
import uvicorn
from click.testing import CliRunner

from harness_api import DATABASE_PATH, GoalAPI
from harness_api.app import create_app
from harness_operator import cli


@pytest.mark.parametrize(
    "args",
    [
        ["create", "--title", "My goal"],
        ["revise", "3", "--title", "Revised"],
        ["complete", "3", "--revision", "1", "--confirmation", "Verified"],
        ["show", "3"],
    ],
)
def test_retired_workspace_spelling_exits_before_accessing_either_destination(
    monkeypatch, tmp_path, args
):
    monkeypatch.chdir(tmp_path)

    def unexpected(*_args, **_kwargs):
        pytest.fail("A retired command must exit before calling HTTP or Codex.")

    monkeypatch.setattr(httpx, "get", unexpected)
    monkeypatch.setattr(subprocess, "run", unexpected)
    result = CliRunner().invoke(cli, ["api", "goals", *args])
    assert result.exit_code == 2
    assert f"operator goal {args[0]}" in result.stderr
    assert not DATABASE_PATH.exists()


def test_workspace_and_http_commands_use_distinct_databases(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    runner = CliRunner()

    def invoke_json(*args):
        result = runner.invoke(cli, args)
        assert result.exit_code == 0, result.output
        return json.loads(result.stdout)

    remote_path = tmp_path / "remote" / DATABASE_PATH
    remote = GoalAPI(remote_path)
    for index in range(1, 4):
        invoke_json("goal", "create", "--title", f"Workspace {index}")
        remote.create_goal(f"Server {index}", status="active")

    with socket.socket() as listener, ThreadPoolExecutor(max_workers=1) as pool:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        monkeypatch.setenv(
            "HARNESS_API_URL", f"http://127.0.0.1:{listener.getsockname()[1]}"
        )
        server = uvicorn.Server(
            uvicorn.Config(create_app(remote_path), ws="none", log_config=None)
        )
        serving = pool.submit(server.run, sockets=[listener])
        try:
            local_rows = invoke_json("goal", "list")
            remote_rows = invoke_json("api", "goals", "list", "--json")
            assert {r["id"]: r["title"] for r in local_rows}[3] == "Workspace 3"
            assert {r["id"]: r["title"] for r in remote_rows}[3] == "Server 3"
            invoke_json(
                "goal", "complete", "3", "--revision", "1", "--confirmation", "Verified"
            )
            assert invoke_json("goal", "show", "3")["status"] == "completed"
            assert remote.get_goal(3)["status"] == "active"
            assert remote.get_goal(3)["completion"] is None
        finally:
            server.should_exit = True
        serving.result()
    unavailable = runner.invoke(cli, ["api", "goals", "list"])
    assert unavailable.exit_code == 1
    assert "Could not reach the Harness API" in unavailable.stderr
    assert not unavailable.stdout


def test_api_goals_list_uses_http_without_auth(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HARNESS_API_URL", raising=False)

    def unexpected_subprocess(*_args, **_kwargs):
        pytest.fail("Direct API commands should not start Codex.")

    def get(url, *, timeout, trust_env):
        assert url == "http://127.0.0.1:8000/goals"
        assert timeout > 0
        assert not trust_env
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json=[
                {
                    "id": 7,
                    "status": "active",
                    "title": "Keep config\n\aprivate",
                    "revision": 1,
                    "operator": "Mira",
                },
                {
                    "id": 8,
                    "status": "draft",
                    "title": None,
                    "revision": None,
                    "operator": None,
                },
            ],
        )

    monkeypatch.setattr(subprocess, "run", unexpected_subprocess)
    monkeypatch.setattr(httpx, "get", get)
    result = CliRunner().invoke(cli, ["api", "goals", "list"])

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        "#7 [active] Keep config private (assigned to Mira)",
        "#8 [draft] (untitled)",
    ]
    assert not DATABASE_PATH.exists()


def test_api_goals_list_uses_configured_url(monkeypatch):
    def get(url, **_kwargs):
        assert url == "http://127.0.0.1:9000/harness/goals"
        return httpx.Response(200, request=httpx.Request("GET", url), json=[])

    monkeypatch.setattr(httpx, "get", get)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["api", "goals", "list"],
        env={"HARNESS_API_URL": "http://127.0.0.1:9000/harness/"},
    )
    assert result.exit_code == 0, result.output
    assert result.stdout == "No saved goals.\n"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        [
            {
                "id": 7,
                "status": "draft",
                "title": "Réviser le guide",
                "revision": None,
                "operator": None,
                "extra": {"tags": ["docs"]},
            }
        ],
    ],
)
def test_api_goals_list_json_prints_full_payload(monkeypatch, payload):
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

    def get(url, **_kwargs):
        return httpx.Response(200, request=httpx.Request("GET", url), content=body)

    monkeypatch.setattr(httpx, "get", get)
    result = CliRunner().invoke(cli, ["api", "goals", "list", "--json"])

    assert result.exit_code == 0, result.output
    assert result.stdout_bytes == body + b"\n"


@pytest.mark.parametrize(
    "url",
    [
        "localhost:8000",
        "file:///tmp/",
        "http://user:secret@localhost",
        "http://localhost?port=9000",
        "http://localhost:99999",
    ],
)
def test_api_goals_list_rejects_invalid_base_url(monkeypatch, url):
    def get(*_args, **_kwargs):
        pytest.fail("The invalid URL should be rejected before a request is made.")

    monkeypatch.setattr(httpx, "get", get)
    result = CliRunner().invoke(cli, ["api", "--url", url, "goals", "list"])

    assert result.exit_code == 2
    assert "Invalid value for --url" in result.stderr
    assert "secret" not in result.output


@pytest.mark.parametrize(
    ("status_code", "body", "message"),
    [(500, {}, "returned HTTP 500"), (200, {}, "returned an invalid goal list")],
)
@pytest.mark.parametrize("options", [[], ["--json"]])
def test_api_goals_list_reports_invalid_responses(
    monkeypatch, status_code, body, message, options
):
    def get(url, **_kwargs):
        return httpx.Response(status_code, request=httpx.Request("GET", url), json=body)

    monkeypatch.setattr(httpx, "get", get)
    result = CliRunner().invoke(cli, ["api", "goals", "list", *options])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert message in result.stderr


def test_api_goals_list_reports_connection_error(monkeypatch):
    def get(url, **_kwargs):
        raise httpx.ConnectError(
            "Connection refused", request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(httpx, "get", get)
    result = CliRunner().invoke(cli, ["api", "goals", "list"])
    assert result.exit_code == 1
    assert "Start it with `make api`." in result.stderr
