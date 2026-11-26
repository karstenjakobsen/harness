"""The complete Slice 10 handoff. Requires a built image and local Codex login."""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest
import uvicorn

from harness_api import GoalAPI, NomadBackend, WorkerNomadBackend, WorkloadSpec
from harness_mcp.worker import create_worker_app, verify_identity

ROOT = Path(__file__).resolve().parents[3]


def worker_image():
    image = os.environ.get("HARNESS_WORKER_IMAGE")
    path = ROOT / ".harness/nomad/worker-image"
    if image is None and path.is_file():
        image = path.read_text().strip()
    if not image:
        pytest.skip("Build the worker with make worker-image.")
    return image


def worker_host():
    configured = os.environ.get("HARNESS_WORKER_HOST")
    if configured:
        return configured
    gateway = subprocess.check_output(
        [
            "docker",
            "network",
            "inspect",
            "bridge",
            "--format",
            "{{(index .IPAM.Config 0).Gateway}}",
        ],
        text=True,
    ).strip()
    with socket.socket() as probe:
        try:
            probe.bind((gateway, 0))
        except OSError:
            pass
        else:
            return gateway
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(("192.0.2.1", 80))
        return probe.getsockname()[0]


@pytest.fixture
def worker_listener():
    host = worker_host()
    with socket.socket() as listener:
        listener.bind((host, 0))
        yield host, listener


def wait_until(check, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.5)
    pytest.fail("Timed out waiting for the worker allocation.")


@pytest.mark.nomad
def test_same_image_ordinary_workload_has_no_login_mount():
    image = worker_image()
    backend = NomadBackend(
        os.environ.get("HARNESS_NOMAD_ADDR", "http://127.0.0.1:14646")
    )
    handle = backend.start(
        "slice10-no-auth-" + uuid4().hex,
        WorkloadSpec(image, ("sh", "-c", "codex --version && sleep 30")),
    )
    try:
        status = wait_until(
            lambda: (
                s
                if (s := backend.inspect(handle)).state in ("running", "failed")
                else None
            )
        )
        assert status.state == "running"
        containers = subprocess.check_output(
            [
                "docker",
                "ps",
                "-aq",
                "--filter",
                "label=com.hashicorp.nomad.alloc_id=" + status.allocation_id,
            ],
            text=True,
        ).split()
        assert containers
        inspected = json.loads(
            subprocess.check_output(["docker", "inspect", *containers], text=True)
        )
        workload = next(c for c in inspected if c["Config"]["Image"] == image)
        assert not any(
            m["Destination"] == "/worker/.codex/auth.json" for m in workload["Mounts"]
        )
        output = subprocess.check_output(["docker", "logs", workload["Id"]], text=True)
        assert "codex-cli 0.166.0" in output
        print(
            f"same-image workload {image} allocation={status.allocation_id} has no login mount"
        )
    finally:
        backend.stop(handle)


@pytest.mark.live
def test_operator_delegates_and_fresh_session_reviews_worker(tmp_path, worker_listener):
    import jwt
    from fastapi.testclient import TestClient

    from harness_api.app import create_app

    image = worker_image()
    address = os.environ.get("HARNESS_NOMAD_ADDR", "http://127.0.0.1:14646")
    bridge, listener = worker_listener
    port = listener.getsockname()[1]
    endpoint = f"http://{bridge}:{port}/mcp"
    executable = Path(sys.executable).with_name("operator")

    def cli(*arguments, timeout=180):
        result = subprocess.run(
            [str(executable), *map(str, arguments)],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    parent = json.loads(cli("goal", "create", "--title", "Build a chess game in Go"))
    child = json.loads(
        cli(
            "goal",
            "create",
            "--title",
            "Verify pinned rook legality",
            "--parent",
            parent["id"],
            "--success-criteria",
            "Two contrasting pinned-rook legality cases are ready for review.",
        )
    )
    operator = json.loads(cli("register", "Reviewer"))
    grant = json.loads(cli("goal", "grant-work", child["id"], operator["id"]))
    api = GoalAPI(tmp_path / ".harness/goals.sqlite3")
    api.work.configure_launcher(image, address, endpoint)
    backend = WorkerNomadBackend(address, image, endpoint)
    keys = jwt.PyJWKClient(address + "/.well-known/jwks.json")
    app = create_worker_app(
        api, backend, bridge, port, lambda token: verify_identity(token, keys)
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host=bridge, port=port, log_level="warning")
    )
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    try:
        wait_until(lambda: server.started, 10)
        cli(
            "ask",
            "--work-grant",
            grant["id"],
            "Prepare two test cases showing when a pinned rook may move and when it may not.",
        )

        def finished():
            items = api.get_goal_activity(child["id"])["work_items"]
            if not items:
                return None
            attempt = items[0]["attempts"][-1]
            return attempt if attempt["state"] in ("failed", "succeeded") else None

        attempt = wait_until(finished)
        if attempt["state"] != "succeeded" or not attempt["result"]:
            from urllib.request import urlopen

            with urlopen(
                f"{address}/v1/client/fs/logs/{attempt['allocation_id']}?task=workload&type=stderr&plain=true",
                timeout=5,
            ) as response:
                diagnostic = response.read().decode()
            with urlopen(
                f"{address}/v1/client/fs/logs/{attempt['allocation_id']}?task=workload&type=stdout&plain=true",
                timeout=5,
            ) as response:
                diagnostic += response.read().decode()
            pytest.fail(
                f"Worker allocation {attempt['allocation_id']} exited {attempt['exit_code']} with result={attempt['result']}. {diagnostic}"
            )
        (item,) = api.get_goal_activity(child["id"])["work_items"]
        assert item["skill_revisions"]
        assert any(
            c["tool"] == "read_skill" and c["outcome"] == "returned"
            for c in attempt["worker_calls"]
        )
        fixture = attempt["result"]["fixture"]
        assert len(fixture["cases"]) == 2
        assert {c["expected_legal"] for c in fixture["cases"]} == {True, False}
        assert not fixture["executed"]
        reply = cli(
            "ask",
            f"Goal {child['id']}. What did the worker deliver, what was verified, and what still needs correction? "
            "Return only JSON with cases (fen, move, expected_legal), tests_executed, needs_correction, and an explanation.",
        )
        review = json.loads(
            reply.strip()
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )
        assert review["tests_executed"] is False, reply
        assert review["explanation"], reply
        fields = ("fen", "move", "expected_legal")
        assert sorted(
            tuple(case[field] for field in fields) for case in review["cases"]
        ) == sorted(
            tuple(case[field] for field in fields) for case in fixture["cases"]
        ), reply
        assert api.get_goal(child["id"])["status"] == "active"
        with TestClient(create_app(tmp_path / ".harness/goals.sqlite3")) as http:
            saved = (
                http.get(f"/goals/{child['id']}/history?view=activity")
                .raise_for_status()
                .json()
            )
            assert saved["work_items"][0]["attempts"][0]["result"] == attempt["result"]

        # Supply a controlled, well-formed incorrect fixture under the real allocation.
        # The harness supplies the fixture so this check does not depend on a worker
        # deciding to make the intended chess mistake.
        run = api.start_run(work_grant_id=grant["id"])["id"]
        call = api.start_tool_call(run, "retry_work", target_work_item_id=item["id"])
        retry = api.work.retry_work(item["id"], attempt["id"], "controlled", call=call)
        api.work.dispatch(retry["attempt_id"], backend)

        def placed():
            latest = api.get_goal_activity(child["id"])["work_items"][0]["attempts"][-1]
            return latest if latest["allocation_id"] else None

        latest = wait_until(placed)
        wrong = {
            "cases": [
                {
                    "fen": "k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1",
                    "move": "e2f2",
                    "expected_legal": True,
                    "reason": "Rooks move horizontally.",
                }
            ],
            "executed": False,
        }
        api.work.worker_call(
            latest["job_id"],
            latest["allocation_id"],
            "submit_work_result",
            {"fixture": wrong},
        )
        correction = cli(
            "ask",
            f"Goal {child['id']}. Review the latest worker result. Is it correct? Explain any error and leave the goal open if correction is needed.",
        )
        assert "f2" in correction.lower(), correction
        assert "king" in correction.lower(), correction
        assert any(
            word in correction.lower()
            for word in ("illegal", "incorrect", "exposes", "expose")
        )
        assert api.get_goal(child["id"])["status"] == "active"
        print(
            json.dumps(
                {
                    "goal_id": child["id"],
                    "work_item_id": item["id"],
                    "delegating_call": attempt["committing_call"],
                    "brief": item["brief"],
                    "assigned_skills": item["skill_revisions"],
                    "worker_calls": attempt["worker_calls"],
                    "image": image,
                    "allocation_id": attempt["allocation_id"],
                    "exit_code": attempt["exit_code"],
                    "fixture": fixture,
                    "fresh_review": review,
                    "controlled_fixture": wrong,
                    "review_of_error": correction,
                    "goal_status": api.get_goal(child["id"])["status"],
                },
                indent=2,
            )
        )
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        for item in api.get_goal_activity(child["id"])["work_items"]:
            for attempt in item["attempts"]:
                if attempt["job_id"]:
                    backend.stop(attempt["job_id"])
        assert not thread.is_alive(), "Worker service did not shut down."


@pytest.mark.nomad
def test_trusted_worker_mount_and_signed_mcp(tmp_path, worker_listener):
    """Exercise the real credential mount and signed transport with a controlled fixture."""
    from urllib.request import Request, urlopen

    import jwt

    from harness_api import OperatorAPI

    image = worker_image()
    address = os.environ.get("HARNESS_NOMAD_ADDR", "http://127.0.0.1:14646")
    host, listener = worker_listener
    port = listener.getsockname()[1]
    endpoint = f"http://{host}:{port}/mcp"
    api = GoalAPI(tmp_path / "db")
    api.work.configure_launcher(image, address, endpoint)
    goal = api.create_goal("Infrastructure fixture")["id"]
    operator = OperatorAPI(tmp_path / "db").register_operator(
        "Infrastructure reviewer"
    )["id"]
    grant = api.grant_work(goal, operator)
    run = api.start_run(work_grant_id=grant["id"])["id"]
    call = api.start_tool_call(
        run, "delegate_work", target_goal_id=goal, target_revision=1
    )
    api.work.delegate_work(
        goal, 1, "Prepare one pinned rook test fixture.", [], "one", call=call
    )
    backend = WorkerNomadBackend(address, image, endpoint)
    keys = jwt.PyJWKClient(address + "/.well-known/jwks.json", timeout=3)
    server = uvicorn.Server(
        uvicorn.Config(
            create_worker_app(
                api, backend, host, port, lambda token: verify_identity(token, keys)
            ),
            host=host,
            port=port,
            log_level="warning",
        )
    )
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    try:
        wait_until(lambda: server.started, 10)

        def running_container():
            attempts = api.get_goal_activity(goal)["work_items"][0]["attempts"]
            allocation = attempts[0]["allocation_id"]
            if not allocation:
                return None
            ids = subprocess.check_output(
                [
                    "docker",
                    "ps",
                    "-q",
                    "--filter",
                    "label=com.hashicorp.nomad.alloc_id=" + allocation,
                ],
                text=True,
            ).split()
            if not ids:
                return None
            containers = json.loads(
                subprocess.check_output(["docker", "inspect", *ids], text=True)
            )
            return next((c for c in containers if c["Config"]["Image"] == image), None)

        container = wait_until(running_container)
        mount = next(
            m
            for m in container["Mounts"]
            if m["Destination"] == "/worker/.codex/auth.json"
        )
        assert not mount["RW"]
        # Capture the task JWT in memory. The test never prints or persists it.
        token = subprocess.check_output(
            ["docker", "exec", container["Id"], "cat", "/secrets/harness.jwt"],
            text=True,
        ).strip()
        job, allocation = verify_identity(token, keys)
        assert not any(
            m["Destination"] in ("/var/run/docker.sock", "/run/docker.sock")
            for m in container["Mounts"]
        )
        probe = """
const http = require("node:http");
const fs = require("node:fs");
const token = fs.readFileSync("/secrets/harness.jwt", "utf8").trim();
const request = http.get({
  socketPath: "/secrets/api.sock",
  path: "/v1/jobs",
  headers: {"X-Nomad-Token": token},
  timeout: 2000
}, response => {
  console.log(response.statusCode);
  response.destroy();
});
request.on("error", () => console.log("unreachable"));
request.on("timeout", () => request.destroy());
"""
        management_status = subprocess.check_output(
            ["docker", "exec", container["Id"], "node", "-e", probe], text=True
        ).strip()
        assert management_status in ("401", "403", "unreachable"), management_status

        def rpc(name, args):
            request = Request(
                endpoint,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "Authorization": "Bearer " + token,
                },
                data=json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": args},
                    }
                ).encode(),
            )
            with urlopen(request, timeout=10) as response:
                result = json.load(response)["result"]
            assert not result.get("isError"), result
            return result

        rpc("get_work_brief", {})
        fixture = {
            "cases": [
                {
                    "fen": "k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1",
                    "move": "e2f2",
                    "expected_legal": False,
                    "reason": "Exposes the king.",
                }
            ],
            "executed": False,
        }
        rpc("submit_work_result", {"fixture": fixture})
        attempt = api.get_goal_activity(goal)["work_items"][0]["attempts"][0]
        assert attempt["result"]["fixture"] == fixture
        assert attempt["allocation_id"] == allocation and attempt["job_id"] == job
        print(
            f"controlled transport fixture image={image} job={job} allocation={allocation} observation={attempt['result']['evidence_id']} read-only login mount verified"
        )
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        attempt = api.get_goal_activity(goal)["work_items"][0]["attempts"][0]
        if attempt["job_id"]:
            backend.stop(attempt["job_id"])
        assert not thread.is_alive(), "Worker service did not shut down."
