"""Seed, inspect a rendered job, then explicitly run the Slice 11 experiment."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import sysconfig
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from jinja2 import Environment, StrictUndefined

DIRECTORY = Path(__file__).resolve().parent


def save_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def owner_cli(receipt, *args):
    receipt.setdefault("owner_commands", []).append(list(map(str, args)))
    result = subprocess.run(
        [receipt["operator_cli"], *map(str, args)],
        cwd=receipt["workspace"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def seed(args):
    executable = shutil.which(args.operator or "operator")
    if executable is None and args.operator is None:
        executable = shutil.which(str(Path(sysconfig.get_path("scripts")) / "operator"))
    if executable is None:
        raise ValueError("Install the owner CLI with make setup or supply --operator.")
    fixture = json.loads(args.fixture.read_text())
    if args.smoke:
        fixture["argv"] = fixture.pop("smoke_argv")
        fixture["image"] = fixture.pop("smoke_image")
        fixture["expected_exit_code"] = fixture.pop("smoke_expected_exit_code")
    else:
        fixture = {
            key: value for key, value in fixture.items() if not key.startswith("smoke_")
        }
        fixture["expected_exit_code"] = 0
    workspace = args.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    if any(workspace.iterdir()):
        raise ValueError("Seed requires a new, empty workspace directory.")
    receipt = {
        "workspace": str(workspace),
        "operator_cli": str(Path(executable).absolute()),
        "attempt_id": args.attempt_id or f"phase2-{uuid4().hex}",
        "job_id": f"phase2-{uuid4().hex}",
        "fixture": fixture,
        "mode": "smoke" if args.smoke else "worker",
        "volume_ids": {},
        "phase": "seeded",
        "execution": None,
    }
    operator = owner_cli(receipt, "register", "phase2-fixture")
    parent = owner_cli(receipt, "goal", "create", "--title", fixture["parent_title"])
    goal = owner_cli(
        receipt,
        "goal",
        "create",
        "--parent",
        parent["id"],
        "--title",
        fixture["goal_title"],
    )
    item = owner_cli(
        receipt,
        "work",
        "create",
        "--goal-id",
        goal["id"],
        "--revision",
        goal["revision"],
        "--operator-id",
        operator["id"],
        "--skill",
        "worker-handoff@1",
        "--brief",
        fixture["brief"],
    )
    attempt = owner_cli(
        receipt, "work", "prepare", item["id"], "--attempt-id", receipt["attempt_id"]
    )
    receipt.update(
        operator_id=operator["id"],
        parent_goal_id=parent["id"],
        goal_id=goal["id"],
        goal_revision=goal["revision"],
        work_item_id=item["id"],
        prepared_attempt=attempt,
    )
    directory = workspace / "phase2"
    directory.mkdir()
    save_json(directory / "receipt.json", receipt)
    return receipt


def render(receipt, receipt_path, args):
    if receipt["phase"] not in ("seeded", "rendered"):
        raise ValueError(
            "Render requires a prepared attempt with no submission started."
        )
    fixture = receipt["fixture"]
    worker = receipt["mode"] == "worker"
    image = args.image or (None if worker else fixture["image"])
    if not image or re.fullmatch(r"(?:[^\s]+@)?sha256:[0-9a-f]{64}", image) is None:
        raise ValueError("Supply a digest-pinned image.")
    filename = fixture["filename"]
    if not filename or Path(filename).name != filename or filename in (".", ".."):
        raise ValueError("The fixture filename must be a single relative filename.")
    argv = ["harness-worker"] if worker else fixture["argv"]
    if not argv or not all(isinstance(value, str) for value in argv):
        raise ValueError(
            "The fixture argv must contain an executable and string arguments."
        )
    # Nomad's Docker driver decodes HCL templates even inside JSON config.
    argv = [value.replace("${", "$${").replace("%{", "%%{") for value in argv]
    metadata = {
        "phase2_attempt_id": receipt["attempt_id"],
        "phase2_work_item_id": str(receipt["work_item_id"]),
        "phase2_run_id": receipt["job_id"],
    }
    volumes = {}
    mounts = []
    config = {
        "image": image,
        "entrypoint": argv[:1],
        "args": argv[1:],
        "volumes": ["local:/workspace"],
        "work_dir": "/workspace",
    }
    task_environment = {"OUTPUT_FILE": filename}
    if worker:
        for name in ("scratch", "runtime"):
            volumes[name] = {
                "Type": "host",
                "AttachmentMode": "file-system",
                "AccessMode": "single-node-reader-only"
                if name == "runtime"
                else "single-node-writer",
                "Source": f"{receipt['job_id']}-{name}",
                "ReadOnly": name == "runtime",
            }
            mounts.append(
                {
                    "Volume": name,
                    "Destination": "/workspace" if name == "scratch" else "/runtime",
                    "ReadOnly": name == "runtime",
                }
            )
        bootstrap = """set -eu
export HARNESS_WORKER_TOKEN="$(cat /runtime/credential)"
export CODEX_HOME=/local/codex-home
mkdir -p "$CODEX_HOME"
cp /runtime/auth.json "$CODEX_HOME/auth.json"
chmod 0600 "$CODEX_HOME/auth.json"
exec harness-worker run --attempt-id "$HARNESS_WORKER_ATTEMPT_ID"
"""
        config = {
            "image": image,
            "entrypoint": ["sh"],
            "args": ["-c", bootstrap],
            "network_mode": "host",
            "work_dir": "/workspace",
        }
        task_environment = {
            "HARNESS_WORKER_ATTEMPT_ID": receipt["attempt_id"],
            "HARNESS_WORKER_MCP_URL": args.mcp_url
            or f"http://127.0.0.1:{args.mcp_port}/mcp",
        }
    environment = Environment(undefined=StrictUndefined)
    template = environment.from_string((DIRECTORY / "job.json.j2").read_text())
    job = json.loads(
        template.render(
            job_id=receipt["job_id"],
            metadata=metadata,
            image=image,
            argv=argv,
            user=f"{os.getuid()}:{os.getgid()}",
            task_environment=task_environment,
            config=config,
            volumes=volumes,
            mounts=mounts,
        )
    )
    job_path = receipt_path.parent / "job.json"
    save_json(job_path, job)
    inspection = owner_cli(receipt, "work", "show", receipt["attempt_id"])
    save_json(receipt_path.parent / "prepared.json", inspection)
    receipt.update(
        phase="rendered",
        image=image,
        job_path=str(job_path),
        job_sha256=hashlib.sha256(job_path.read_bytes()).hexdigest(),
        scratch="workload/local",
        metadata=metadata,
        mcp_port=args.mcp_port,
        mcp_url=args.mcp_url or f"http://127.0.0.1:{args.mcp_port}/mcp",
    )
    save_json(receipt_path, receipt)
    return receipt


def request(client, method, path, **kwargs):
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    return response


def retained_job(client, receipt):
    response = client.get(f"job/{receipt['job_id']}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    job = response.json()
    if job.get("Meta") != receipt["metadata"]:
        raise ValueError("The job ID is owned by another experiment.")
    return job


def allocations(client, receipt):
    return request(client, "GET", f"job/{receipt['job_id']}/allocations").json() or []


def process_start_time(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except FileNotFoundError:
        return None


def stop_owned_server(server, owner):
    try:
        descriptor = os.pidfd_open(server["pid"])
    except ProcessLookupError:
        return
    try:
        if select.select([descriptor], [], [], 0)[0]:
            return
        if process_start_time(server["pid"]) != server["start_time"]:
            return
        if owner:
            environment = (
                Path(f"/proc/{server['pid']}/environ").read_bytes().split(b"\0")
            )
            if f"HARNESS_PHASE2_RUNTIME_OWNER={owner}".encode() not in environment:
                raise RuntimeError(
                    "The recorded MCP process has a different runtime owner."
                )
        signal.pidfd_send_signal(descriptor, signal.SIGTERM)
        if not select.select([descriptor], [], [], 10)[0]:
            signal.pidfd_send_signal(descriptor, signal.SIGKILL)
            if not select.select([descriptor], [], [], 5)[0]:
                raise RuntimeError("The owned MCP process could not be stopped.")
    except ProcessLookupError:
        pass
    finally:
        os.close(descriptor)


def legacy_runtime(receipt, directory):
    # Older interrupted receipts recorded the workspace and port. Match the exact
    # owner CLI invocation before recording a process identity for cleanup.
    servers = []
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal():
            continue
        try:
            arguments = (process / "cmdline").read_bytes().decode().split("\0")
            command = ["work", "--workspace", receipt["workspace"], "serve-mcp"]
            index = arguments.index("work")
            if (
                receipt["operator_cli"] in arguments[:2]
                and arguments[index : index + 4] == command
                and arguments[arguments.index("--port") + 1] == str(receipt["mcp_port"])
            ):
                pid = int(process.name)
                servers.append({"pid": pid, "start_time": process_start_time(pid)})
        except (
            FileNotFoundError,
            ProcessLookupError,
            PermissionError,
            ValueError,
            IndexError,
        ):
            continue
    return {
        "owner": None,
        "servers": servers,
        "grant_pending": (directory / "runtime/credential").exists(),
        "grant_id": None,
        "cleaned": False,
    }


def cleanup_runtime(receipt, receipt_path):
    if receipt["mode"] != "worker":
        return
    directory = receipt_path.parent
    info = receipt.get("runtime")
    if info is None:
        if not (directory / "runtime").exists():
            return
        info = legacy_runtime(receipt, directory)
        receipt["runtime"] = info
        save_json(receipt_path, receipt)
    if info.get("cleaned"):
        return
    if info.get("grant_id") or info.get("grant_pending"):
        current = owner_cli(receipt, "work", "show", receipt["attempt_id"])["attempt"][
            "grant_id"
        ]
        if current is not None and (
            info.get("grant_id") is None or current == info["grant_id"]
        ):
            owner_cli(receipt, "work", "revoke-credential", receipt["attempt_id"])
        info["grant_pending"] = False
        info["grant_id"] = None
        save_json(receipt_path, receipt)
    for server in info["servers"]:
        stop_owned_server(server, info["owner"])
    runtime = directory / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    info["cleaned"] = True
    save_json(receipt_path, receipt)


PARENT_GUARD = """import ctypes, os, signal, sys
parent = int(sys.argv[1])
if ctypes.CDLL(None).prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
    raise SystemExit("Cannot bind the MCP process lifetime to its runner")
if os.getppid() != parent:
    raise SystemExit(1)
os.execv(sys.argv[2], sys.argv[2:])
"""


def worker_runtime(client, receipt, receipt_path, auth_file):
    directory = receipt_path.parent
    scratch = directory / "scratch"
    runtime = directory / "runtime"
    info = {
        "owner": uuid4().hex,
        "servers": [],
        "grant_pending": False,
        "grant_id": None,
        "cleaned": False,
    }
    receipt["runtime"] = info
    save_json(receipt_path, receipt)
    scratch.mkdir(mode=0o700)
    runtime.mkdir(mode=0o700)
    owner_cli(receipt, "work", "bind-scratch", receipt["attempt_id"], scratch)
    info["grant_pending"] = True
    save_json(receipt_path, receipt)
    grant = owner_cli(
        receipt,
        "work",
        "issue-credential",
        receipt["attempt_id"],
        "--output",
        runtime / "credential",
    )
    info.update(grant_id=grant["id"], grant_pending=False)
    save_json(receipt_path, receipt)
    shutil.copyfile(auth_file, runtime / "auth.json")
    (runtime / "auth.json").chmod(0o600)
    ready = [
        node
        for node in request(client, "GET", "nodes").json()
        if node["Status"] == "ready"
        and node.get("Drivers", {}).get("docker", {}).get("Healthy")
    ]
    if len(ready) != 1:
        raise RuntimeError(
            "The worker experiment requires one ready Docker-capable Nomad client."
        )
    for name in ("scratch", "runtime"):
        volume = {
            "Name": f"{receipt['job_id']}-{name}",
            "Namespace": "default",
            "NodeID": ready[0]["ID"],
            "HostPath": str(directory / name),
            "RequestedCapabilities": [
                {
                    "AccessMode": "single-node-reader-only"
                    if name == "runtime"
                    else "single-node-writer",
                    "AttachmentMode": "file-system",
                }
            ],
        }
        registered = request(
            client, "PUT", "volume/host/register", json={"Volume": volume}
        ).json()["Volume"]
        receipt["volume_ids"][name] = registered["ID"]
        save_json(receipt_path, receipt)
    command = [
        receipt["operator_cli"],
        "work",
        "--workspace",
        receipt["workspace"],
        "serve-mcp",
        "--host",
        "0.0.0.0"
        if urlsplit(receipt["mcp_url"]).hostname not in ("127.0.0.1", "localhost")
        else "127.0.0.1",
        "--allowed-host",
        "127.0.0.1:*",
        "--allowed-host",
        f"{urlsplit(receipt['mcp_url']).hostname}:*",
        "--port",
        str(receipt["mcp_port"]),
    ]
    with (directory / "evidence/worker-mcp.log").open("w") as log:
        server = subprocess.Popen(
            [sys.executable, "-c", PARENT_GUARD, str(os.getpid()), *command],
            stdout=log,
            stderr=log,
            env={**os.environ, "HARNESS_PHASE2_RUNTIME_OWNER": info["owner"]},
        )
    info["servers"].append(
        {"pid": server.pid, "start_time": process_start_time(server.pid)}
    )
    save_json(receipt_path, receipt)
    with httpx.Client(timeout=0.5, trust_env=False) as probe:
        deadline = time.monotonic() + 15
        while True:
            if server.poll() is not None:
                raise RuntimeError("Worker MCP stopped during startup.")
            try:
                if (
                    probe.get(f"http://127.0.0.1:{receipt['mcp_port']}/mcp").status_code
                    == 401
                ):
                    return server
            except httpx.TransportError:
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("Worker MCP did not become ready.")
            time.sleep(0.1)


def export_artifact(
    receipt, destination, expected_hash=None, expected_artifact_id=None
):
    with TemporaryDirectory(dir=destination.parent) as temporary:
        output = Path(temporary) / "artifact"
        artifact = owner_cli(
            receipt, "work", "artifact", receipt["goal_id"], "--output", output
        )
        if expected_artifact_id is not None and artifact["id"] != expected_artifact_id:
            raise RuntimeError(
                "The goal's latest artifact differs from this attempt's saved artifact."
            )
        actual = hashlib.sha256(output.read_bytes()).hexdigest()
        if actual != artifact["sha256"] or (
            expected_hash is not None and actual != expected_hash
        ):
            raise RuntimeError("Harness retrieval changed the saved artifact bytes.")
        output.replace(destination)
    return artifact


def verify_worker(receipt, evidence):
    inspection = owner_cli(receipt, "work", "show", receipt["attempt_id"])
    save_json(evidence / "harness-after.json", inspection)
    for tool in ("get_work_brief", "read_skill", "submit_work_result"):
        if not any(
            call["tool"] == tool and call["outcome"] == "returned"
            for call in inspection["calls"]
        ):
            raise RuntimeError(f"The real worker has no successful {tool} call.")
    events = [
        json.loads(line)
        for line in (evidence / "stdout.log").read_text().splitlines()
        if line.startswith("{")
    ]
    sessions = sum(event.get("type") == "thread.started" for event in events)
    if sessions != 1:
        raise RuntimeError(f"Expected one real worker session, observed {sessions}.")
    artifact = inspection["artifact"]
    if artifact is None or (
        artifact["operator_id"],
        artifact["goal_revision"],
        artifact["work_item_id"],
    ) != (receipt["operator_id"], receipt["goal_revision"], receipt["work_item_id"]):
        raise RuntimeError("The saved worker artifact has unexpected attribution.")
    export_artifact(
        receipt,
        evidence / receipt["fixture"]["filename"],
        artifact["sha256"],
        artifact["id"],
    )
    return {
        "worker_sessions": sessions,
        "artifact_id": artifact["id"],
        "grant_id": artifact["grant_id"],
    }


def cleanup(client, receipt):
    if retained_job(client, receipt) is None:
        cleanup_volumes(client, receipt)
        return {"job_removed": True, "scratch_removed": True}
    request(client, "DELETE", f"job/{receipt['job_id']}?purge=false")
    deadline = time.monotonic() + 30
    while True:
        placed = allocations(client, receipt)
        if all(
            allocation["ClientStatus"] in ("complete", "failed")
            for allocation in placed
        ):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "Cleanup could not confirm stopped allocations within 30 seconds."
            )
        time.sleep(0.2)
    for allocation in placed:
        request(client, "GET", f"client/allocation/{allocation['ID']}/gc")
    request(client, "DELETE", f"job/{receipt['job_id']}?purge=true")
    if retained_job(client, receipt) is not None:
        raise RuntimeError("The experiment job is still registered after cleanup.")
    cleanup_volumes(client, receipt)
    return {"job_removed": True, "scratch_removed": True}


def cleanup_volumes(client, receipt):
    if receipt["mode"] != "worker":
        return
    directory = Path(receipt["job_path"]).parent
    for name, identifier in receipt["volume_ids"].items():
        response = client.get(f"volume/host/{identifier}")
        if response.status_code == 404:
            continue
        response.raise_for_status()
        volume = response.json()
        if volume.get("HostPath") != str(directory / name):
            raise RuntimeError("Refusing to clean up another experiment's volume.")
        request(client, "DELETE", f"volume/host/{identifier}/delete")
    if (directory / "scratch").exists():
        shutil.rmtree(directory / "scratch")


def check_result(client, receipt, receipt_path):
    evidence = receipt_path.parent / "evidence"
    outcome = receipt["execution"]
    allocation = json.loads((evidence / "allocation.json").read_text())
    for stream in ("stdout", "stderr"):
        logs = request(
            client,
            "GET",
            f"client/fs/logs/{allocation['ID']}",
            params={"task": "workload", "type": stream, "plain": "true"},
        )
        (evidence / f"{stream}.log").write_bytes(logs.content)
    filename = receipt["fixture"]["filename"]
    if receipt["mode"] == "worker":
        events = [
            json.loads(line)
            for line in (evidence / "stdout.log").read_text().splitlines()
            if line.startswith("{")
        ]
        outcome["worker_sessions"] = sum(
            event.get("type") == "thread.started" for event in events
        )
        outcome["ai_operator_sessions"] = sum(
            command[0] == "ask"
            or (command[:2] == ["goal", "create"] and "--title" not in command)
            for command in receipt["owner_commands"]
        )
        if outcome["ai_operator_sessions"] != 0:
            raise RuntimeError("The experiment started an AI operator session.")
        outcome.update(verify_worker(receipt, evidence))
        content = (evidence / filename).read_bytes()
        outcome["file_sha256"] = hashlib.sha256(content).hexdigest()
    else:
        source = f"{receipt['scratch']}/{filename}"
        stat = client.get(f"client/fs/stat/{allocation['ID']}", params={"path": source})
        missing = stat.status_code == 404 or (
            stat.is_error and "no such file or directory" in stat.text
        )
        content = None
        if not missing:
            stat.raise_for_status()
            file = request(
                client,
                "GET",
                f"client/fs/cat/{allocation['ID']}",
                params={"path": source},
            )
            content = file.content
            (evidence / filename).write_bytes(content)
            outcome["file_sha256"] = hashlib.sha256(content).hexdigest()
    if (
        outcome["exit_code"] != receipt["fixture"]["expected_exit_code"]
        or outcome["task_restarts"] != 0
    ):
        raise RuntimeError(f"Unexpected task outcome {outcome}")
    if outcome["exit_code"] == 0:
        expected = ("\n".join(receipt["fixture"]["cities"]) + "\n").encode()
        if content != expected:
            raise RuntimeError(
                "The recovered file differs from the fixture's exact city lines."
            )
    elif outcome["file_sha256"] is not None:
        raise RuntimeError("The failure case unexpectedly produced a deliverable.")
    goal = owner_cli(receipt, "goal", "show", receipt["goal_id"])
    if (goal["revision"], goal["status"]) != (
        receipt["goal_revision"],
        "active",
    ):
        raise RuntimeError("The goal changed during the experiment.")
    inspection = owner_cli(receipt, "work", "show", receipt["attempt_id"])
    save_json(evidence / "harness-after.json", inspection)
    receipt["result_checked"] = True
    save_json(receipt_path, receipt)


def verify_after_cleanup(receipt, receipt_path):
    outcome = receipt["execution"]
    receipt["phase"] = "verify_pending"
    outcome["verified"] = False
    save_json(receipt_path, receipt)
    try:
        if receipt["mode"] == "worker":
            destination = (
                receipt_path.parent
                / "evidence"
                / f"after-cleanup-{receipt['fixture']['filename']}"
            )
            export_artifact(
                receipt, destination, outcome["file_sha256"], outcome["artifact_id"]
            )
        outcome.pop("verification_error", None)
        outcome.pop("cleanup_error", None)
        outcome["verified"] = True
        receipt["phase"] = "finished"
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        outcome["verification_error"] = str(error)
    save_json(receipt_path, receipt)
    return receipt


def run(receipt, receipt_path, args):
    if args.timeout <= 0:
        raise ValueError("Timeout must be positive.")
    if receipt.get("nomad_address") and receipt["nomad_address"] != args.nomad_addr:
        raise ValueError("Use the original Nomad destination for this receipt.")
    if receipt["phase"] == "finished":
        return receipt
    # Reopen receipts written before terminal phases were introduced.
    outcome = receipt.get("execution") or {}
    if receipt["phase"] == "running" and (
        outcome.get("exit_code") is not None
        or outcome.get("state") in ("complete", "failed")
    ):
        receipt["phase"] = "observed"
        if outcome.get("artifact_id") and outcome.get("cleanup", {}).get(
            "scratch_removed"
        ):
            receipt["phase"] = "verify_pending"
    if receipt["phase"] == "verify_pending":
        return verify_after_cleanup(receipt, receipt_path)
    if receipt["phase"] not in ("rendered", "running", "observed", "cleanup_pending"):
        raise ValueError("Render the job before running it.")
    fresh = receipt["phase"] == "rendered"
    payload = None
    if fresh:
        payload = Path(receipt["job_path"]).read_bytes()
        if hashlib.sha256(payload).hexdigest() != receipt["job_sha256"]:
            raise ValueError(
                "The rendered job changed. Render again before submitting."
            )
        outcome = {
            "allocation_id": None,
            "exit_code": None,
            "file_sha256": None,
            "verified": False,
        }
        receipt.update(
            phase="running", nomad_address=args.nomad_addr, execution=outcome
        )
        save_json(receipt_path, receipt)
    evidence = receipt_path.parent / "evidence"
    evidence.mkdir(exist_ok=True)
    headers = (
        {"X-Nomad-Token": os.environ["NOMAD_TOKEN"]}
        if os.environ.get("NOMAD_TOKEN")
        else {}
    )
    started = time.monotonic()
    server = None
    with httpx.Client(
        base_url=args.nomad_addr.rstrip("/") + "/v1/",
        headers=headers,
        timeout=5,
        trust_env=False,
    ) as client:
        try:
            if fresh:
                if receipt["mode"] == "worker":
                    server = worker_runtime(
                        client, receipt, receipt_path, args.auth_file
                    )
                if retained_job(client, receipt) is None:
                    receipt["submission_started"] = True
                    save_json(receipt_path, receipt)
                    try:
                        request(
                            client,
                            "POST",
                            "jobs",
                            content=payload,
                            headers={"Content-Type": "application/json"},
                        )
                    except httpx.TransportError, httpx.HTTPStatusError:
                        if retained_job(client, receipt) is None:
                            raise RuntimeError(
                                "Submission outcome is unknown. Inspect the same job ID before retrying."
                            ) from None
                wait_for_exit(client, receipt, receipt_path, started + args.timeout)
            elif receipt["phase"] == "running":
                outcome["error"] = (
                    "The runner was interrupted. Recovery stops this attempt and cleans up its runtime. Use a fresh attempt to execute again."
                )
            if receipt["phase"] == "observed":
                check_result(client, receipt, receipt_path)
        except (
            ValueError,
            OSError,
            RuntimeError,
            subprocess.SubprocessError,
            httpx.HTTPError,
        ) as error:
            outcome["error"] = str(error)
        finally:
            if fresh:
                outcome["workload_seconds"] = round(time.monotonic() - started, 3)
            cleanup_errors = []
            try:
                cleanup_runtime(receipt, receipt_path)
                if server is not None:
                    server.wait(timeout=5)
            except (
                ValueError,
                OSError,
                RuntimeError,
                subprocess.SubprocessError,
                httpx.HTTPError,
            ) as error:
                cleanup_errors.append(str(error))
            try:
                outcome["cleanup"] = cleanup(client, receipt)
            except (
                ValueError,
                OSError,
                RuntimeError,
                subprocess.SubprocessError,
                httpx.HTTPError,
            ) as error:
                cleanup_errors.append(str(error))
            if cleanup_errors:
                outcome["cleanup_error"] = "\n".join(cleanup_errors)
                outcome["verified"] = False
                receipt["phase"] = "cleanup_pending"
            else:
                outcome.pop("cleanup_error", None)
                receipt["phase"] = (
                    "verify_pending" if receipt.get("result_checked") else "finished"
                )
            save_json(receipt_path, receipt)
    if receipt["phase"] == "verify_pending":
        return verify_after_cleanup(receipt, receipt_path)
    return receipt


def wait_for_exit(client, receipt, receipt_path, deadline):
    evidence = receipt_path.parent / "evidence"
    outcome = receipt["execution"]
    while True:
        placed = allocations(client, receipt)
        save_json(evidence / "allocations.json", placed)
        if len(placed) > 1:
            raise RuntimeError("Expected exactly one allocation.")
        if placed:
            allocation = request(client, "GET", f"allocation/{placed[0]['ID']}").json()
            outcome.update(
                allocation_id=allocation["ID"],
                state=allocation["ClientStatus"],
                allocation_count=len(placed),
            )
            save_json(evidence / "allocation.json", allocation)
            if allocation["ClientStatus"] in ("complete", "failed"):
                task = (allocation.get("TaskStates") or {}).get("workload") or {}
                outcome.update(
                    task_restarts=task.get("Restarts"),
                    exit_code=next(
                        (
                            event.get("ExitCode")
                            for event in reversed(task.get("Events") or [])
                            if event["Type"] == "Terminated"
                        ),
                        None,
                    ),
                )
                receipt["phase"] = "observed"
                save_json(receipt_path, receipt)
                return
            save_json(receipt_path, receipt)
        if time.monotonic() >= deadline:
            raise RuntimeError("Allocation did not finish before the bounded deadline.")
        time.sleep(0.2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="step", required=True)
    seed_parser = commands.add_parser("seed")
    seed_parser.add_argument("--workspace", type=Path, required=True)
    seed_parser.add_argument("--fixture", type=Path, default=DIRECTORY / "cities.json")
    seed_parser.add_argument("--attempt-id")
    seed_parser.add_argument("--operator")
    seed_parser.add_argument(
        "--smoke",
        action="store_true",
        help="Use the scripted city writer for a scheduler smoke test.",
    )
    render_parser = commands.add_parser("render")
    render_parser.add_argument("--receipt", type=Path, required=True)
    render_parser.add_argument("--image")
    render_parser.add_argument("--mcp-port", type=int, default=8001)
    render_parser.add_argument(
        "--mcp-url",
        help="Worker-reachable URL, including /mcp, for Docker Desktop or remote clients.",
    )
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--receipt", type=Path, required=True)
    run_parser.add_argument("--nomad-addr", default="http://127.0.0.1:14646")
    run_parser.add_argument(
        "--auth-file",
        type=Path,
        default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        / "auth.json",
    )
    run_parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    try:
        if args.step == "seed":
            receipt = seed(args)
        else:
            receipt_path = args.receipt.resolve()
            with receipt_path.with_suffix(".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                receipt = json.loads(receipt_path.read_text())
                operation = render if args.step == "render" else run
                receipt = operation(receipt, receipt_path, args)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return int(
            receipt["execution"] is not None and not receipt["execution"]["verified"]
        )
    except (ValueError, OSError, subprocess.SubprocessError, httpx.HTTPError) as error:
        print(f"phase2: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
