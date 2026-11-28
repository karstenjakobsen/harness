import argparse
import json
import os
import runpy
import shutil
import signal
import socket
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import experiment
import httpx
import pytest

from harness_api import DATABASE_PATH, WorkAPI, WorkAuthorizationError


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "git").symlink_to(shutil.which("git"))
    monkeypatch.setenv("PATH", str(binaries))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-login"))
    monkeypatch.setenv("HARNESS_NOMAD_ADDR", "http://127.0.0.1:1")
    workspace = tmp_path / "workspace"
    script = experiment.DIRECTORY / "experiment.py"

    def invoke(*args, check=True):
        return subprocess.run(
            [sys.executable, str(script), *map(str, args)],
            capture_output=True,
            text=True,
            check=check,
            timeout=30,
        )

    result = invoke("seed", "--workspace", workspace)
    receipt = json.loads(result.stdout)
    return workspace, invoke, receipt


def test_seed_and_render_are_offline_checkpoint_with_no_sessions(prepared):
    workspace, invoke, seeded = prepared
    path = workspace / "phase2/receipt.json"
    image = "sha256:" + "a" * 64
    rendered = json.loads(invoke("render", "--receipt", path, "--image", image).stdout)
    assert seeded["mode"] == rendered["mode"] == "worker"
    assert "argv" not in seeded["fixture"] and "smoke_argv" not in seeded["fixture"]
    assert seeded["execution"] is rendered["execution"] is None
    prepared_attempt = json.loads((path.parent / "prepared.json").read_text())
    assert prepared_attempt["attempt"] == seeded["prepared_attempt"]
    assert prepared_attempt["calls"] == [] and prepared_attempt["artifact"] is None
    job = json.loads((path.parent / "job.json").read_text())
    assert job["EnforceIndex"] is True and job["JobModifyIndex"] == 0
    (group,) = job["Job"]["TaskGroups"]
    (task,) = group["Tasks"]
    assert group["Count"] == 1 and group["RestartPolicy"]["Attempts"] == 0
    assert group["ReschedulePolicy"] == {"Attempts": 0, "Unlimited": False}
    assert task["Config"]["image"] == image
    assert "security_opt" not in task["Config"]
    assert "harness-worker run" in task["Config"]["args"][1]
    assert "cities.txt" not in task["Config"]["args"][1]
    assert task["Env"]["HARNESS_WORKER_ATTEMPT_ID"] == seeded["attempt_id"]
    assert {mount["Destination"] for mount in task["VolumeMounts"]} == {
        "/workspace",
        "/runtime",
    }
    assert group["Volumes"]["scratch"]["AccessMode"] == "single-node-writer"
    assert not (path.parent / "runtime").exists()
    repeated = invoke("seed", "--workspace", workspace, check=False)
    assert repeated.returncode == 1 and "empty workspace" in repeated.stderr
    assert json.loads(path.read_text()) == rendered


@pytest.mark.parametrize(
    ("engine", "auth", "model", "effort"),
    [
        ("codex", "api-key", "gpt-5.6-luna", "low"),
        ("codex", "auth-json", "gpt-5.5", "medium"),
        ("kiro", "api-key", "claude-sonnet-4.6", "low"),
        ("kiro", "api-key", "claude-opus-4.8", "xhigh"),
    ],
)
def test_worker_launch_configurations(
    prepared, tmp_path, monkeypatch, engine, auth, model, effort
):
    workspace, invoke, seeded = prepared
    first = workspace / "phase2/receipt.json"
    attempt = json.loads(
        invoke("prepare", "--receipt", first, "--attempt-id", "other-attempt").stdout
    )
    assert attempt["work_item_id"] == seeded["work_item_id"]
    assert attempt["goal_revision"] == seeded["goal_revision"]
    assert attempt["job_id"] != seeded["job_id"]
    assert attempt["prepared_attempt"]["id"] != seeded["prepared_attempt"]["id"]
    path = Path(attempt["receipt_path"])
    image = "sha256:" + "a" * 64
    rendered = json.loads(
        invoke(
            "render",
            "--receipt",
            path,
            "--image",
            image,
            "--worker",
            engine,
            "--auth",
            auth,
            "--model",
            model,
            "--effort",
            effort,
        ).stdout
    )
    assert rendered["launch"] == {
        "worker": engine,
        "auth": auth,
        "requested_model": model,
        "requested_effort": effort,
        "brief_only": False,
    }
    job = json.loads(Path(rendered["job_path"]).read_text())
    task = job["Job"]["TaskGroups"][0]["Tasks"][0]
    environment = task["Env"] | {"HARNESS_WORKER_TOKEN": "harness-fixture"}
    keys = {
        "OPENAI_API_KEY": "unused-fixture",
        "CODEX_API_KEY": "codex-fixture",
        "KIRO_API_KEY": "kiro-fixture",
    }
    for name, key in keys.items():
        monkeypatch.setenv(name, key)
    saved = tmp_path / "auth.json"
    saved.write_text('{"fixture": "saved-login"}')
    credential = experiment.worker_auth(rendered, saved)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    experiment.stage_worker_auth(runtime, credential)
    (staged,) = runtime.iterdir()
    assert staged.stat().st_mode & 0o777 == 0o600
    assert not any(
        value in json.dumps(job) + json.dumps(rendered) for value in keys.values()
    )
    worker_directory = experiment.DIRECTORY.parent / "worker"
    monkeypatch.syspath_prepend(str(worker_directory))
    worker = runpy.run_path(str(worker_directory / f"{engine}_worker.py"))
    other_engine = "kiro" if engine == "codex" else "codex"
    with pytest.raises(ValueError, match=f"This worker image runs {engine}"):
        worker["cli_environment"](
            environment | keys | {"HARNESS_WORKER_ENGINE": other_engine}
        )
    if auth == "api-key":
        key_name = experiment.PROVIDER_KEYS[engine]
        assert staged.name == "provider-key" and staged.read_text() == keys[key_name]
        assert (
            key_name in task["Config"]["args"][1]
            and "auth.json" not in task["Config"]["args"][1]
        )
        monkeypatch.delenv(key_name)
        with pytest.raises(ValueError, match=key_name):
            experiment.worker_auth(rendered, saved)
        with pytest.raises(ValueError, match=key_name):
            worker["cli_environment"](environment)
        assert worker["cli_environment"](environment | keys)[key_name] == keys[key_name]
    else:
        assert staged.name == "auth.json" and staged.read_bytes() == saved.read_bytes()
        assert "auth.json" in task["Config"]["args"][1]
        assert not keys.keys() & worker["cli_environment"](environment | keys).keys()
        with pytest.raises(FileNotFoundError):
            experiment.worker_auth(rendered, tmp_path / "missing.json")
    argv = worker["command"](attempt["attempt_id"], environment)
    assert argv[argv.index("--model") + 1] == model
    if engine == "kiro":
        assert argv[argv.index("--effort") + 1] == effort
        assert "--require-mcp-startup" in argv
        environment["KIRO_HOME"] = str(tmp_path / "kiro")
        worker["prepare_kiro"](environment)
        config = tmp_path / "kiro/settings/mcp.json"
        assert config.stat().st_mode & 0o777 == 0o600
        assert json.loads(config.read_text())["mcpServers"]["worker"]["headers"] == {
            "Authorization": "Bearer harness-fixture"
        }
        with pytest.raises(ValueError, match="effort"):
            worker["command"](
                attempt["attempt_id"], environment | {"HARNESS_WORKER_EFFORT": "ultra"}
            )
    else:
        assert f'model_reasoning_effort="{effort}"' in argv
    assert "harness-fixture" not in argv


def test_kiro_rejects_codex_saved_login(prepared):
    workspace, invoke, _ = prepared
    result = invoke(
        "render",
        "--receipt",
        workspace / "phase2/receipt.json",
        "--worker",
        "kiro",
        "--auth",
        "auth-json",
        "--model",
        "claude-sonnet-4.6",
        "--effort",
        "low",
        check=False,
    )
    assert result.returncode == 1 and "Kiro api-key" in result.stderr


def test_worker_events_keep_complete_kiro_events_from_partial_capture():
    stdout = (
        b'{"type":"harness.worker_cli","version":"kiro-cli 3.7.0"}\n'
        b'{"type":"sessionUpdate","data":{"sessionId":"one","update":'
        b'{"sessionUpdate":"config_option_update","configOptions":'
        b'[{"id":"model","currentValue":"claude-opus-4.8"},'
        b'{"id":"effortLevel","currentValue":"low"}]}}}\n'
        b'{"method":"session/update","params":{"sessionId":"one"}}\n'
        b'{"method":"session/update"'
    )
    assert experiment.worker_events(stdout, {"worker": "kiro"}) == (
        1,
        "kiro-cli 3.7.0",
        True,
        {"model": "claude-opus-4.8", "effort": "low"},
    )


def test_render_json_encodes_arguments_and_blocks_changed_job(prepared):
    workspace, _, receipt = prepared
    path = workspace / "phase2/receipt.json"
    receipt["mode"] = "smoke"
    receipt["fixture"]["image"] = json.loads(
        (experiment.DIRECTORY / "cities.json").read_text()
    )["smoke_image"]
    receipt["fixture"]["argv"] = ["printf", "%s", 'a"quote\n${literal}%{literal}']
    result = experiment.render(
        receipt,
        path,
        argparse.Namespace(image=None, mcp_port=8001, mcp_url=None),
    )
    job = json.loads(Path(result["job_path"]).read_text())
    task = job["Job"]["TaskGroups"][0]["Tasks"][0]
    assert task["Config"]["args"] == ["%s", 'a"quote\n$${literal}%%{literal}']
    Path(result["job_path"]).write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        experiment.run(
            result,
            path,
            argparse.Namespace(timeout=10, nomad_addr="http://127.0.0.1:1"),
        )
    assert result["execution"] is None


def test_smoke_fixture_writes_exact_city_bytes(tmp_path):
    fixture = json.loads((experiment.DIRECTORY / "cities.json").read_text())
    subprocess.run(
        fixture["smoke_argv"],
        cwd=tmp_path,
        env={**os.environ, "OUTPUT_FILE": fixture["filename"]},
        check=True,
    )
    assert (tmp_path / fixture["filename"]).read_bytes() == (
        "\n".join(fixture["cities"]) + "\n"
    ).encode()


@pytest.mark.parametrize("exit_code", [0, 7])
def test_run_recovers_lost_registration_and_cleans_only_its_job(
    prepared, monkeypatch, exit_code
):
    import hashlib

    workspace, _, receipt = prepared
    receipt["mode"] = "smoke"
    receipt["fixture"]["image"] = json.loads(
        (experiment.DIRECTORY / "cities.json").read_text()
    )["smoke_image"]
    receipt["fixture"]["argv"] = json.loads(
        (experiment.DIRECTORY / "cities.json").read_text()
    )["smoke_argv"]
    receipt["fixture"]["expected_exit_code"] = exit_code
    path = workspace / "phase2/receipt.json"
    receipt = experiment.render(
        receipt,
        path,
        argparse.Namespace(image=None, mcp_port=8001, mcp_url=None),
    )
    payload = Path(receipt["job_path"]).read_bytes()
    expected = ("\n".join(receipt["fixture"]["cities"]) + "\n").encode()
    job_path = f"/v1/job/{receipt['job_id']}"
    state = {"registered": False, "posts": 0, "gc": 0}

    def respond(request):
        route = request.url.path
        if route == "/v1/jobs":
            assert request.content == payload
            state.update(registered=True, posts=state["posts"] + 1)
            raise httpx.ReadTimeout("Registration response lost", request=request)
        if route == job_path and request.method == "DELETE":
            if request.url.params.get("purge") == "true":
                state["registered"] = False
            return httpx.Response(200, json={})
        if route == job_path:
            return (
                httpx.Response(200, json={"Meta": receipt["metadata"]})
                if state["registered"]
                else httpx.Response(404)
            )
        allocation = {
            "ID": "one-allocation",
            "ClientStatus": "complete" if exit_code == 0 else "failed",
            "TaskStates": {
                "workload": {
                    "Restarts": 0,
                    "Events": [{"Type": "Terminated", "ExitCode": exit_code}],
                }
            },
        }
        if route == job_path + "/allocations":
            return httpx.Response(200, json=[allocation])
        if route == "/v1/allocation/one-allocation":
            return httpx.Response(200, json=allocation)
        if route == "/v1/client/fs/logs/one-allocation":
            return httpx.Response(200, content=b"")
        if route == "/v1/client/fs/stat/one-allocation":
            return (
                httpx.Response(500, text="stat cities.txt: no such file or directory")
                if exit_code
                else httpx.Response(200, json={"Name": "cities.txt"})
            )
        if route == "/v1/client/fs/cat/one-allocation":
            return (
                httpx.Response(404)
                if exit_code
                else httpx.Response(200, content=expected)
            )
        assert route == "/v1/client/allocation/one-allocation/gc"
        state["gc"] += 1
        return httpx.Response(200, json={})

    client = httpx.Client
    monkeypatch.setattr(
        experiment.httpx,
        "Client",
        lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs),
    )
    args = argparse.Namespace(timeout=2, nomad_addr="http://nomad.test")
    finished = experiment.run(receipt, path, args)
    assert finished["execution"]["verified"]
    assert finished["execution"]["exit_code"] == exit_code
    assert state == {"registered": False, "posts": 1, "gc": 1}
    assert experiment.run(finished, path, args) == finished
    assert state["posts"] == 1
    if exit_code == 0:
        assert (
            finished["execution"]["file_sha256"] == hashlib.sha256(expected).hexdigest()
        )


@pytest.fixture
def worker_experiment(prepared, tmp_path):
    workspace, invoke, receipt = prepared
    path = workspace / "phase2/receipt.json"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    receipt = experiment.render(
        receipt,
        path,
        argparse.Namespace(
            image="sha256:" + "a" * 64,
            mcp_port=port,
            mcp_url=None,
        ),
    )
    auth_file = tmp_path / "test-auth.json"
    auth_file.write_text('{"fixture": true}')
    state = {"posts": 0, "job": None, "volumes": {}, "hold": False}
    endpoint = f"http://127.0.0.1:{port}/mcp"

    def worker():
        credential = (path.parent / "runtime/credential").read_text()
        with httpx.Client(
            headers={
                "Authorization": f"Bearer {credential}",
                "Accept": "application/json, text/event-stream",
            },
            trust_env=False,
        ) as client:
            for tool, arguments in (
                ("get_work_brief", {}),
                ("read_skill", {"id": "worker-handoff", "revision": 1}),
            ):
                reply = client.post(
                    endpoint,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": tool, "arguments": arguments},
                    },
                )
                assert reply.status_code == 200 and not reply.json()["result"].get(
                    "isError"
                )
            (path.parent / "scratch/cities.txt").write_text(
                "\n".join(receipt["fixture"]["cities"]) + "\n"
            )
            reply = client.post(
                endpoint,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "submit_work_result",
                        "arguments": {"relative_path": "cities.txt"},
                    },
                },
            )
            assert not reply.json()["result"].get("isError")

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, data):
            state.setdefault("requests", []).append((self.command, self.path))
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def do_POST(self):
            assert self.path == "/v1/jobs"
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["job"] = payload["Job"]
            state["posts"] += 1
            if not state["hold"]:
                worker()
            self.reply(200, {})

        def do_PUT(self):
            volume = json.loads(self.rfile.read(int(self.headers["Content-Length"])))[
                "Volume"
            ]
            volume["ID"] = volume["Name"]
            state["volumes"][volume["ID"]] = volume
            self.reply(200, {"Volume": volume})

        def do_GET(self):
            route = self.path.partition("?")[0]
            if route == "/v1/nodes":
                self.reply(
                    200,
                    [
                        {
                            "ID": "fixture-node",
                            "Status": "ready",
                            "Drivers": {"docker": {"Healthy": True}},
                        }
                    ],
                )
            elif route.startswith("/v1/volume/host/"):
                volume = state["volumes"].get(route.rsplit("/", 1)[1])
                self.reply(200 if volume else 404, volume)
            elif route.endswith("/allocations"):
                self.reply(
                    200,
                    []
                    if state["hold"]
                    else [{"ID": "fixture-allocation", "ClientStatus": "complete"}],
                )
            elif route.startswith("/v1/allocation/"):
                self.reply(
                    200,
                    {
                        "ID": "fixture-allocation",
                        "ClientStatus": "complete",
                        "TaskStates": {
                            "workload": {
                                "Restarts": 0,
                                "Events": [{"Type": "Terminated", "ExitCode": 0}],
                            }
                        },
                    },
                )
            elif route.startswith("/v1/client/fs/logs/"):
                self.reply(200, {"type": "thread.started"})
            elif route.endswith("/gc"):
                self.reply(200, {})
            else:
                assert route == f"/v1/job/{receipt['job_id']}"
                self.reply(200 if state["job"] else 404, state["job"])

        def do_DELETE(self):
            if state["posts"] and not state["hold"]:
                saved = json.loads(path.read_text())["execution"]
                assert saved["allocation_id"] == "fixture-allocation"
                assert saved["exit_code"] == 0
            if self.path.startswith("/v1/volume/host/"):
                del state["volumes"][self.path.split("/")[-2]]
            elif "purge=true" in self.path:
                state["job"] = None
            self.reply(200, {})

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            args = argparse.Namespace(
                timeout=15,
                nomad_addr=f"http://127.0.0.1:{server.server_port}",
                auth_file=auth_file,
            )
            yield path, receipt, args, state, endpoint, invoke
        finally:
            server.shutdown()
            thread.join()


@pytest.mark.parametrize("legacy_receipt", [False, True])
def test_failed_final_export_retries_without_another_submission(
    worker_experiment, legacy_receipt
):
    path, receipt, args, state, _, _ = worker_experiment
    evidence = path.parent / "evidence"
    evidence.mkdir()
    blocked = evidence / "after-cleanup-cities.txt"
    blocked.mkdir()
    failed = experiment.run(receipt, path, args)
    assert not failed["execution"]["verified"]
    assert failed["execution"]["allocation_id"] == "fixture-allocation"
    assert failed["execution"]["exit_code"] == 0
    assert state["posts"] == 1 and state["job"] is None
    saved = json.loads(path.read_text())
    assert saved["phase"] == "verify_pending"
    if legacy_receipt:
        saved["phase"] = "running"
        saved["execution"]["cleanup_error"] = saved["execution"].pop(
            "verification_error"
        )
        experiment.save_json(path, saved)
    blocked.rmdir()
    requests = list(state["requests"])
    retried = experiment.run(json.loads(path.read_text()), path, args)
    assert retried["execution"]["verified"]
    assert state["posts"] == 1
    assert state["requests"] == requests


def test_api_key_delivery_survives_unparseable_native_activity(
    worker_experiment, tmp_path
):
    path, receipt, args, state, _, _ = worker_experiment
    receipt = experiment.render(
        receipt,
        path,
        argparse.Namespace(
            image=receipt["image"],
            mcp_port=receipt["mcp_port"],
            mcp_url=receipt["mcp_url"],
            worker="kiro",
            model="claude-sonnet-4.6",
            effort="low",
            auth="api-key",
        ),
    )
    args.api_key_file = tmp_path / "kiro-key"
    args.api_key_file.write_text("kiro-provider-fixture\n")
    finished = experiment.run(receipt, path, args)
    outcome = finished["execution"]
    assert outcome["verified"], outcome.get("error")
    assert outcome["activity_capture"]["stdout"] == "incomplete"
    assert outcome["worker_sessions"] is None and outcome["exit_code"] == 0
    assert outcome["artifact_id"] and outcome["grant_id"]
    assert not (path.parent / "runtime").exists()
    assert not (path.parent / "scratch").exists()
    assert state["posts"] == 1
    assert "kiro-provider-fixture" not in path.read_text()


def test_killed_runner_recovers_its_credential_server_and_runtime(worker_experiment):
    path, receipt, args, state, endpoint, invoke = worker_experiment
    state["hold"] = True
    runner = subprocess.Popen(
        [
            sys.executable,
            str(experiment.DIRECTORY / "experiment.py"),
            "run",
            "--receipt",
            str(path),
            "--nomad-addr",
            args.nomad_addr,
            "--auth-file",
            str(args.auth_file),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 15
        while state["posts"] == 0:
            assert runner.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.05)
        credential = (path.parent / "runtime/credential").read_text()
        api = WorkAPI(Path(receipt["workspace"]) / DATABASE_PATH)
        assert api.resolve_attempt(credential)["id"] == receipt["attempt_id"]
        runner.kill()
        runner.wait(timeout=5)
        invoke(
            "run",
            "--receipt",
            path,
            "--nomad-addr",
            args.nomad_addr,
            "--auth-file",
            args.auth_file,
            check=False,
        )
        with pytest.raises(WorkAuthorizationError):
            api.resolve_attempt(credential)
        with pytest.raises(httpx.TransportError):
            httpx.get(endpoint, timeout=1, trust_env=False)
        assert not (path.parent / "runtime").exists()
        assert state["posts"] == 1
    finally:
        if runner.poll() is None:
            runner.kill()
            runner.wait(timeout=5)
        try:
            os.killpg(runner.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_server_cleanup_checks_process_identity_before_signalling():
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        env={**os.environ, "HARNESS_PHASE2_RUNTIME_OWNER": "owned-fixture"},
    )
    try:
        server = {"pid": process.pid, "start_time": "0"}
        experiment.stop_owned_server(server, "owned-fixture")
        assert process.poll() is None
        server["start_time"] = experiment.process_start_time(process.pid)
        with pytest.raises(RuntimeError, match="different runtime owner"):
            experiment.stop_owned_server(server, "another-run")
        assert process.poll() is None
        experiment.stop_owned_server(server, "owned-fixture")
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
