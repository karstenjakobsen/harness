"""Worker acceptance on local Nomad. Only the live cases start Codex."""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest
import uvicorn

from harness_api import GoalAPI, NomadBackend, WorkerNomadBackend, WorkloadSpec
from harness_mcp.worker import create_worker_app, verify_identity

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", autouse=True)
def local_worker_cluster():
    if "HARNESS_NOMAD_ADDR" not in os.environ:
        subprocess.run(["make", "nomad-up"], cwd=ROOT, check=True)
    if "HARNESS_WORKER_IMAGE" not in os.environ:
        subprocess.run(["make", ".harness/nomad/worker-image"], cwd=ROOT, check=True)


def worker_image():
    image = os.environ.get("HARNESS_WORKER_IMAGE")
    path = ROOT / ".harness/nomad/worker-image"
    if image is None and path.is_file():
        image = path.read_text().strip()
    if not image:
        pytest.fail("Build the worker with make worker-image.")
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

    class ReviewBackend(WorkerNomadBackend):
        controlled_result = False

        def _configure_job(self, job):
            super()._configure_job(job)
            if self.controlled_result:
                job["TaskGroups"][0]["Tasks"][1]["Config"].update(
                    entrypoint=["sleep"], args=["120"]
                )

    backend = ReviewBackend(address, image, endpoint)
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
            diagnostic = task_log(address, attempt, "stderr")
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
            http.headers["Authorization"] = (
                "Bearer " + api.work.owner_http_token_file.read_text()
            )
            saved = (
                http.get(f"/goals/{child['id']}/history?view=activity")
                .raise_for_status()
                .json()
            )
            assert saved["work_items"][0]["attempts"][0]["result"] == attempt["result"]

        # Supply a controlled, well-formed incorrect fixture under the real allocation.
        # The harness supplies the fixture so this check does not depend on a worker
        # deciding to make the intended chess mistake.
        backend.controlled_result = True
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


def task_log(address, attempt, stream):
    request = Request(
        f"{address}/v1/client/fs/logs/{attempt['allocation_id']}?task=workload&type={stream}&plain=true"
    )
    if path := os.environ.get("HARNESS_NOMAD_TOKEN_FILE"):
        request.add_unredirected_header("X-Nomad-Token", Path(path).read_text().strip())
    with urlopen(request, timeout=5) as response:
        return response.read().decode()


@contextmanager
def serve(app, listener):
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    try:
        wait_until(lambda: server.started, 10)
        yield
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        assert not thread.is_alive()


@contextmanager
def handoff(tmp_path, worker_listener, brief, backend_class=WorkerNomadBackend):
    import jwt

    from harness_api import OperatorAPI
    from harness_api.app import create_app

    path = tmp_path / "goals.sqlite3"
    api = GoalAPI(path)
    goal = api.create_goal("Prepare a file", status="active")["id"]
    operator = OperatorAPI(path).register_operator("File reviewer")["id"]
    grant = api.grant_work(goal, operator)
    host, listener = worker_listener
    port = listener.getsockname()[1]
    address = os.environ.get("HARNESS_NOMAD_ADDR", "http://127.0.0.1:14646")
    image = worker_image()
    endpoint = f"http://{host}:{port}/mcp"
    api.work.configure_launcher(image, address, endpoint)
    backend = backend_class(address, image, endpoint)
    keys = jwt.PyJWKClient(address + "/.well-known/jwks.json", timeout=5)
    worker = create_worker_app(
        api, backend, host, port, lambda token: verify_identity(token, keys)
    )
    with socket.socket() as owner:
        owner.bind(("127.0.0.1", 0))
        owner_url = f"http://127.0.0.1:{owner.getsockname()[1]}"
        with serve(create_app(path), owner), serve(worker, listener):
            run = api.start_run(work_grant_id=grant["id"])["id"]
            call = api.start_tool_call(
                run, "delegate_work", target_goal_id=goal, target_revision=1
            )
            result = api.work.delegate_work(
                goal, 1, brief, [], "file", call=call, result_type="text_file"
            )
            try:
                api.finish_tool_call(
                    call,
                    "returned",
                    returned_goals=[
                        {
                            "goal_id": goal,
                            "revision": 1,
                            "status": None,
                            "observation_ids": [],
                            "decision": None,
                        }
                    ],
                )
                api.finish_run(run, "succeeded")
                yield api, goal, address, owner_url
            finally:
                for attempt in api.get_goal_activity(goal)["work_items"][0]["attempts"]:
                    if attempt["id"] == result["attempt_id"] and attempt["job_id"]:
                        backend.stop(attempt["job_id"])


def terminal_attempt(api, goal):
    (item,) = api.get_goal_activity(goal)["work_items"]
    (attempt,) = item["attempts"]
    return (
        attempt
        if attempt["state"] in ("succeeded", "failed", "declined", "stopped")
        else None
    )


CITY_BRIEF = "Create a UTF-8 file named `cities.txt` containing København, Aarhus, Odense, Aalborg, and Esbjerg, one city per line, in any order. Submit the file as your deliverable."


@pytest.mark.live
@pytest.mark.city_file
def test_danish_city_file_handoff(tmp_path, worker_listener, monkeypatch):
    # Every operator adapter invokes codex on PATH. Count and fail any host launch.
    trap = tmp_path / "codex"
    trap.write_text('#!/bin/sh\necho started >> "$0.calls"\nexit 1\n')
    trap.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    started = time.monotonic()
    with handoff(tmp_path, worker_listener, CITY_BRIEF) as (
        api,
        goal,
        address,
        owner_url,
    ):

        def worker_mount():
            (item,) = api.get_goal_activity(goal)["work_items"]
            (attempt,) = item["attempts"]
            if not attempt["allocation_id"]:
                return None
            ids = subprocess.check_output(
                [
                    "docker",
                    "ps",
                    "-aq",
                    "--filter",
                    "ancestor=" + worker_image(),
                    "--filter",
                    "label=com.hashicorp.nomad.alloc_id=" + attempt["allocation_id"],
                ],
                text=True,
            ).split()
            if not ids:
                return None
            (container,) = ids
            mounts = json.loads(
                subprocess.check_output(
                    ["docker", "inspect", "--format", "{{json .Mounts}}", container]
                )
            )
            return next(
                m for m in mounts if m["Destination"] == "/worker/.codex/auth.json"
            )

        assert wait_until(worker_mount)["RW"] is False
        attempt = wait_until(lambda: terminal_attempt(api, goal), 180)
        assert attempt["exit_code"] == 0, task_log(address, attempt, "stderr")
        assert (
            task_log(address, attempt, "stdout")
            .splitlines()
            .count("Worker Codex sessions started=1")
            == 1
        )
        assert not trap.with_suffix(".calls").exists()
        saved = subprocess.check_output(
            [
                sys.executable,
                "-I",
                str(Path(__file__).with_name("read_city_file.py")),
                str(goal),
            ],
            cwd=tmp_path,
            env={
                "HARNESS_OWNER_URL": owner_url,
                "HARNESS_OWNER_TOKEN_FILE": str(api.work.owner_http_token_file),
            },
            text=True,
            timeout=10,
        )
        print(saved.strip())
        print(
            f"warm handoff={time.monotonic() - started:.2f}s worker Codex sessions=1 operator Codex sessions=0"
        )


@pytest.mark.nomad
def test_worker_isolation_and_scoped_mcp(tmp_path, worker_listener):
    class IsolationBackend(WorkerNomadBackend):
        def _configure_job(self, job):
            super()._configure_job(job)
            # Same worker network, identity and guard. The fixed probe requires no login.
            group = job["TaskGroups"][0]
            del group["Volumes"]["codex-login"]
            task = group["Tasks"][1]
            task["VolumeMounts"] = [
                m for m in task["VolumeMounts"] if m["Volume"] != "codex-login"
            ]
            task["Config"].update(entrypoint=["sleep"], args=["120"])

    with handoff(
        tmp_path, worker_listener, "Exercise the scoped endpoint.", IsolationBackend
    ) as (api, goal, address, owner_url):
        owner_request = Request(f"{owner_url}/goals/{goal}")
        owner_request.add_unredirected_header(
            "Authorization", "Bearer " + api.work.owner_http_token_file.read_text()
        )
        with urlopen(owner_request, timeout=5) as response:
            assert json.load(response)["id"] == goal

        def container():
            attempt = api.get_goal_activity(goal)["work_items"][0]["attempts"][0]
            if terminal_attempt(api, goal):
                pytest.fail(
                    f"Isolation worker exited before the check: {attempt['state']}"
                )
            if attempt["state"] != "running":
                return None
            return subprocess.check_output(
                [
                    "docker",
                    "ps",
                    "-q",
                    "--filter",
                    "label=com.hashicorp.nomad.alloc_id=" + attempt["allocation_id"],
                    "--filter",
                    "ancestor=" + worker_image(),
                ],
                text=True,
            ).strip()

        worker = wait_until(container)
        inspect = json.loads(subprocess.check_output(["docker", "inspect", worker]))[0]
        assert not any(
            m["Destination"]
            in (
                "/worker/.codex/auth.json",
                "/secrets/guard-acl",
                "/var/run/docker.sock",
                "/run/docker.sock",
            )
            for m in inspect["Mounts"]
        )
        from urllib.parse import urlsplit

        with Path(__file__).with_name("worker_isolation.mjs").open() as script:
            output = subprocess.check_output(
                [
                    "docker",
                    "exec",
                    "-i",
                    worker,
                    "node",
                    "--input-type=module",
                    "-",
                    str(urlsplit(address).port),
                    str(urlsplit(owner_url).port),
                    str(goal),
                ],
                stdin=script,
                text=True,
                timeout=30,
            )
        print(output.strip())
        (attempt,) = api.get_goal_activity(goal)["work_items"][0]["attempts"]
        assert attempt["result"]["text_file"] == {
            "filename": "probe.txt",
            "content": "ready\n",
        }
        assert any(
            c["tool"] == "get_work_brief" and c["outcome"] == "returned"
            for c in attempt["worker_calls"]
        )
        print(
            f"launcher registered and inspected {attempt['job_id']} allocation={attempt['allocation_id']} observation={attempt['result']['evidence_id']} owner HTTP=200"
        )
