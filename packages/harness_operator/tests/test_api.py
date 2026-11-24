import json
import subprocess

import httpx
import pytest
from click.testing import CliRunner

from harness_api import DATABASE_PATH
from harness_operator import cli


def test_explicit_goal_commands_require_api_prefix(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    def unexpected_codex(*_args, **_kwargs):
        pytest.fail("Explicit goal commands should not start Codex.")

    monkeypatch.setattr(subprocess, "run", unexpected_codex)
    for args in (
        ["create", "--title", "My goal"],
        ["revise", "1", "--title", "Revised"],
        ["complete", "1", "--revision", "1", "--confirmation", "Verified"],
        ["show", "1"],
    ):
        assert runner.invoke(cli, ["goal", *args]).exit_code == 2
    assert not DATABASE_PATH.exists()

    result = runner.invoke(cli, ["api", "goals", "create", "--title", "My goal"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"] == "active"
    assert DATABASE_PATH.is_file()


def test_explicit_api_url_cannot_redirect_a_write_to_local_workspace(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        cli,
        [
            "api",
            "--url",
            "http://localhost:9000",
            "goals",
            "create",
            "--title",
            "My goal",
        ],
    )
    assert result.exit_code == 2
    assert "--url applies to 'goals list'" in result.stderr
    assert not DATABASE_PATH.exists()


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
