"""Exercise the owner CLI and real worker MCP from a cold workspace."""

import asyncio
import json
import os
import shutil
import signal
import socket
import subprocess
import sysconfig
import time
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


@pytest.fixture
def owner(tmp_path):
    workspace = tmp_path / "owner"
    workspace.mkdir()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    # Skill import uses Git. Execution tools and scheduler clients are unavailable.
    (binaries / "git").symlink_to(shutil.which("git"))
    environment = {
        **os.environ,
        "PATH": str(binaries),
        "CODEX_HOME": str(tmp_path / "no-login"),
        "DOCKER_HOST": "unix:///unavailable/docker.sock",
        "HARNESS_NOMAD_ADDR": "http://127.0.0.1:1",
    }
    executable = Path(sysconfig.get_path("scripts")) / "operator"

    def invoke(*args, success=True):
        result = subprocess.run(
            [str(executable), *map(str, args)],
            cwd=workspace,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert (result.returncode == 0) == success, result.stderr
        return json.loads(result.stdout) if success else result

    operator = invoke("register", "Builder")
    goal = invoke("goal", "create", "--title", "Prepare a real file")
    item = invoke(
        "work",
        "create",
        "--goal-id",
        goal["id"],
        "--revision",
        goal["revision"],
        "--operator-id",
        operator["id"],
        "--brief",
        "Write a real result.txt.",
        "--skill",
        "worker-handoff@1",
    )
    return workspace, environment, executable, invoke, goal, item


def test_prepare_and_show_work_offline_in_separate_processes(owner):
    workspace, _, executable, invoke, goal, item = owner
    attempt = invoke("work", "prepare", item["id"], "--attempt-id", "manual-1")
    assert attempt["id"] == "manual-1"
    assert attempt["work_item_id"] == item["id"]
    assert invoke("work", "prepare", item["id"], "--attempt-id", "manual-1") == attempt
    record = invoke("work", "show", "manual-1")
    assert record["attempt"] == attempt
    assert record["work_item"] == item
    assert record["calls"] == [] and record["artifact"] is None
    for field in (
        "scratch_path",
        "grant_id",
        "container_id",
        "launched_at",
        "exit_code",
    ):
        assert attempt[field] is None
    assert invoke("goal", "show", goal["id"])["revision"] == goal["revision"]
    conflict_item = invoke(
        "work",
        "create",
        "--goal-id",
        goal["id"],
        "--revision",
        goal["revision"],
        "--operator-id",
        item["operator_id"],
        "--brief",
        "Another assignment.",
    )
    conflict = invoke(
        "work",
        "prepare",
        conflict_item["id"],
        "--attempt-id",
        "manual-1",
        success=False,
    )
    assert "different work item" in conflict.stderr
    assert invoke("work", "show", "manual-1")["attempt"] == attempt
    retired = invoke(
        "work", "start", item["id"], "--attempt-id", "manual-1", success=False
    )
    assert "No such command" in retired.stderr
    help_result = subprocess.run(
        [str(executable), "work", "--help"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "prepare" in help_result.stdout
    assert "start" not in help_result.stdout


def test_manual_cli_handoff_over_real_http_survives_cleanup_and_revocation(
    owner, tmp_path
):
    workspace, environment, executable, invoke, goal, item = owner
    attempt_id = "manual-mcp"
    invoke("work", "prepare", item["id"], "--attempt-id", attempt_id)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    credential_file = tmp_path / "credential"

    # Invoke from outside the owner workspace to exercise explicit destination.
    def selected(*args):
        result = subprocess.run(
            [str(executable), "work", "--workspace", str(workspace), *map(str, args)],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        return result

    selected("bind-scratch", attempt_id, scratch)
    grant = selected("issue-credential", attempt_id, "--output", credential_file)
    credential = credential_file.read_text()
    assert credential not in grant.stdout + grant.stderr
    assert credential_file.stat().st_mode & 0o777 == 0o600
    assert json.loads(grant.stdout)["attempt_id"] == attempt_id
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    endpoint = f"http://127.0.0.1:{port}/mcp"
    log = tmp_path / "server.log"
    with log.open("w") as stream:
        server = subprocess.Popen(
            [
                str(executable),
                "work",
                "--workspace",
                str(workspace),
                "serve-mcp",
                "--port",
                str(port),
            ],
            cwd=tmp_path,
            env=environment,
            stdout=stream,
            stderr=stream,
        )
        try:
            deadline = time.monotonic() + 15
            with httpx.Client(timeout=0.5, trust_env=False) as probe:
                while True:
                    assert server.poll() is None, log.read_text()
                    try:
                        if probe.get(endpoint).status_code == 401:
                            break
                    except httpx.TransportError:
                        pass
                    assert time.monotonic() < deadline, log.read_text()
                    time.sleep(0.05)

            content = "København\nAarhus\nOdense\nAalborg\nEsbjerg\n".encode()

            async def handoff():
                async with (
                    httpx.AsyncClient(
                        headers={"Authorization": f"Bearer {credential}"},
                        trust_env=False,
                    ) as http,
                    streamable_http_client(endpoint, http_client=http) as (
                        reader,
                        writer,
                        _,
                    ),
                    ClientSession(reader, writer) as session,
                ):
                    await session.initialize()
                    assert {
                        tool.name for tool in (await session.list_tools()).tools
                    } == {
                        "get_work_brief",
                        "list_skills",
                        "read_skill",
                        "submit_work_result",
                    }
                    brief = await session.call_tool("get_work_brief", {})
                    assert not brief.isError
                    assert brief.structuredContent["attempt_id"] == attempt_id
                    assert brief.structuredContent["work_item"] == item
                    assert (
                        brief.structuredContent["goal"]["revision"] == goal["revision"]
                    )
                    assert not (await session.call_tool("list_skills", {})).isError
                    assert not (
                        await session.call_tool(
                            "read_skill", {"id": "worker-handoff", "revision": 1}
                        )
                    ).isError
                    (scratch / "result.txt").write_bytes(content)
                    saved = await session.call_tool(
                        "submit_work_result", {"relative_path": "result.txt"}
                    )
                    assert not saved.isError
                    artifact = saved.structuredContent
                    shutil.rmtree(scratch)
                    retry = await session.call_tool(
                        "submit_work_result", {"relative_path": "result.txt"}
                    )
                    assert retry.structuredContent == artifact
                    output = tmp_path / "recovered.txt"
                    assert (
                        invoke("work", "artifact", goal["id"], "--output", output)
                        == artifact
                    )
                    assert output.read_bytes() == content
                    selected("revoke-credential", attempt_id)
                    # A fresh grant never restores authority to the old credential.
                    selected(
                        "issue-credential",
                        attempt_id,
                        "--output",
                        tmp_path / "replacement",
                    )
                    denied = await http.post(
                        endpoint,
                        headers={"Accept": "application/json, text/event-stream"},
                        json={
                            "jsonrpc": "2.0",
                            "id": 99,
                            "method": "tools/call",
                            "params": {"name": "get_work_brief", "arguments": {}},
                        },
                    )
                    assert denied.status_code == 401
                    selected("revoke-credential", attempt_id)
                return artifact

            artifact = asyncio.run(handoff())
            record = invoke("work", "show", attempt_id)
            assert record["artifact"] == artifact
            assert artifact["operator_id"] == item["operator_id"]
            assert artifact["grant_id"] == json.loads(grant.stdout)["id"]
            assert artifact["goal_revision"] == goal["revision"]
            assert all(
                record["attempt"][field] is None
                for field in ("container_id", "launched_at", "exit_code", "exited_at")
            )
            assert [call["tool"] for call in record["calls"]] == [
                "tools/list",
                "get_work_brief",
                "list_skills",
                "read_skill",
                "submit_work_result",
                "submit_work_result",
                "authenticate_worker",
            ]
            assert record["calls"][-1]["outcome"] == "denied"
            assert credential not in json.dumps(record)
            after = invoke("goal", "show", goal["id"])
            assert (
                after["status"] == goal["status"]
                and after["revision"] == goal["revision"]
            )
            recovered = tmp_path / "after-revoke.txt"
            invoke("work", "artifact", goal["id"], "--output", recovered)
            assert recovered.read_bytes() == content
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
                pytest.fail("Worker MCP failed to stop within ten seconds")
    assert server.returncode in (0, -signal.SIGTERM), log.read_text()
    assert "Application shutdown complete" in log.read_text()
    assert credential not in log.read_text()
    assert not (tmp_path / ".harness").exists()
