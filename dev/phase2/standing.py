"""Inspect a worker delivery, explicitly deploy it, and observe a standing service."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import experiment
import httpx
from jinja2 import Environment, StrictUndefined

DIRECTORY = Path(__file__).resolve().parent
SHELL_IMAGE = "docker.io/library/busybox@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec"
POLL_SECONDS = 1
CORRECTION_SECONDS = 3
SHUTDOWN_SECONDS = 4
SAMPLE_SECONDS = 0.1
STARTUP_SECONDS = 10
TERMINAL = {"complete", "failed"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def service_path(worker_path):
    return worker_path.parent / "service/receipt.json"


def remove_staging(path):
    for name in ("delivery", "data"):
        directory = path.parent / name
        if directory.exists():
            directory.chmod(0o700)
            shutil.rmtree(directory)


def verify_handoff(worker, worker_path):
    result = worker.get("execution") or {}
    if (
        worker["phase"] != "finished"
        or not result.get("verified")
        or result.get("exit_code") != 0
        or result.get("worker_sessions") != 1
        or result.get("ai_operator_sessions") != 0
        or not worker.get("runtime", {}).get("cleaned")
        or any((worker_path.parent / name).exists() for name in ("scratch", "runtime"))
    ):
        raise ValueError("Require one successful worker and completed runtime cleanup.")
    inspection = experiment.owner_cli(worker, "work", "show", worker["attempt_id"])
    artifact = inspection["artifact"]
    if (
        inspection["attempt"]["id"] != worker["attempt_id"]
        or inspection["attempt"]["work_item_id"] != worker["work_item_id"]
        or inspection["attempt"]["grant_id"] is not None
        or inspection["work_item"]["id"] != worker["work_item_id"]
        or inspection["work_item"]["goal_id"] != worker["goal_id"]
        or inspection["work_item"]["goal_revision"] != worker["goal_revision"]
        or artifact is None
        or artifact["id"] != result["artifact_id"]
        or artifact["sha256"] != result["file_sha256"]
        or artifact["attempt_id"] != worker["attempt_id"]
        or artifact["work_item_id"] != worker["work_item_id"]
        or artifact["goal_id"] != worker["goal_id"]
        or artifact["goal_revision"] != worker["goal_revision"]
        or artifact["relative_path"] != "maintain-mode.sh"
        or artifact["operator_id"] != worker["operator_id"]
        or artifact["grant_id"] != result["grant_id"]
    ):
        raise ValueError(
            "The saved artifact or revoked attempt has different provenance."
        )
    goal = experiment.owner_cli(worker, "goal", "show", worker["goal_id"])
    if (goal["status"], goal["revision"], goal["duration"]) != (
        "active",
        worker["goal_revision"],
        "standing",
    ):
        raise ValueError("The standing goal changed.")
    return inspection


def checkpoint(worker, worker_path, image):
    if re.fullmatch(r"(?:[^\s]+@)?sha256:[0-9a-f]{64}", image) is None:
        raise ValueError("Supply a digest-pinned shell image.")
    path = service_path(worker_path)
    if path.exists():
        saved = json.loads(path.read_text())
        if saved["phase"] != "checkpoint":
            raise ValueError(
                "This service has already entered submission. Inspect or clean it up."
            )
        if saved["image"] != image:
            raise ValueError("The checkpoint already selects another shell image.")
        verify_handoff(worker, worker_path)
        validate_checkpoint(saved)
        return saved
    inspection = verify_handoff(worker, worker_path)
    directory = path.parent
    directory.mkdir(exist_ok=True)
    delivery = directory / "delivery"
    data = directory / "data"
    # A failed checkpoint can be retried before there has been any submission.
    try:
        delivery.mkdir(exist_ok=True)
        delivery.chmod(0o700)
        data.mkdir(exist_ok=True)
        artifact = experiment.export_artifact(
            worker,
            delivery / "maintain-mode.sh",
            inspection["artifact"]["sha256"],
            inspection["artifact"]["id"],
        )
        (delivery / "maintain-mode.sh").chmod(0o444)
        delivery.chmod(0o555)
        files = {}
        for name in ("target", "sibling"):
            file = data / name
            file.write_text(f"Slice 12 {name} contents must remain unchanged.\n")
            file.chmod(0o644)
            files[name] = {"sha256": digest(file), "initial_mode": "0644"}
        identifier = f"phase2-service-{uuid4().hex}"
        metadata = {
            "phase2_attempt_id": worker["attempt_id"],
            "phase2_artifact_id": str(artifact["id"]),
            "phase2_goal_revision": str(worker["goal_revision"]),
            "phase2_script_sha256": artifact["sha256"],
            "phase2_run_id": identifier,
        }
        volumes = {
            name: {
                "Type": "host",
                "AttachmentMode": "file-system",
                "AccessMode": "single-node-reader-only"
                if name == "delivery"
                else "single-node-writer",
                "Source": f"{identifier}-{name}",
                "ReadOnly": name == "delivery",
            }
            for name in ("delivery", "data")
        }
        template = Environment(undefined=StrictUndefined).from_string(
            (DIRECTORY / "service.json.j2").read_text()
        )
        job = json.loads(
            template.render(
                job_id=identifier,
                metadata=metadata,
                image=image,
                volumes=volumes,
                user=f"{os.getuid()}:{os.getgid()}",
            )
        )
        experiment.save_json(directory / "job.json", job)
        experiment.save_json(directory / "attempt.json", inspection)
        experiment.save_json(directory / "export.json", artifact)
        saved = {
            "phase": "checkpoint",
            "job_id": identifier,
            "metadata": metadata,
            "worker_job_id": worker["job_id"],
            "attempt_id": worker["attempt_id"],
            "goal_id": worker["goal_id"],
            "goal_revision": worker["goal_revision"],
            "artifact": artifact,
            "image": image,
            "files": files,
            "job_path": str(directory / "job.json"),
            "job_sha256": digest(directory / "job.json"),
            "script_path": str(delivery / "maintain-mode.sh"),
            "volume_ids": {},
            "allocation_id": None,
            "nomad_address": worker.get("nomad_address"),
            "timing": {
                "worker_poll_seconds": POLL_SECONDS,
                "correction_deadline_seconds": CORRECTION_SECONDS,
                "startup_deadline_seconds": STARTUP_SECONDS,
                "shutdown_window_seconds": SHUTDOWN_SECONDS,
                "sample_seconds": SAMPLE_SECONDS,
            },
            "observations": {},
            "verified": False,
        }
        experiment.save_json(path, saved)
        return saved
    except BaseException:
        if not path.exists():
            remove_staging(path)
        raise


def validate_checkpoint(saved):
    payload = Path(saved["job_path"]).read_bytes()
    if hashlib.sha256(payload).hexdigest() != saved["job_sha256"]:
        raise ValueError("The checkpoint job changed.")
    if digest(Path(saved["script_path"])) != saved["artifact"]["sha256"]:
        raise ValueError("The checkpoint script changed.")
    if Path(saved["script_path"]).stat().st_mode & 0o222:
        raise ValueError("The staged script must be read-only.")
    return payload


def current_allocation(client, saved, stopped=False):
    job = experiment.retained_job(client, saved)
    if job is None:
        raise RuntimeError("The service job is absent; recover with cleanup.")
    placed = experiment.allocations(client, saved)
    if len(placed) != 1:
        raise RuntimeError(f"Expected one service allocation, observed {len(placed)}.")
    allocation = experiment.request(
        client, "GET", f"allocation/{placed[0]['ID']}"
    ).json()
    if saved["allocation_id"] and saved["allocation_id"] != allocation["ID"]:
        raise RuntimeError("Nomad replaced the original service allocation.")
    task = (allocation.get("TaskStates") or {}).get("service") or {}
    if task.get("Restarts", 0) != 0:
        raise RuntimeError("Nomad restarted the service task.")
    if stopped:
        if not job.get("Stop") or allocation["ClientStatus"] not in TERMINAL:
            raise RuntimeError("The service or a replacement is still running.")
    elif (
        job.get("Stop")
        or allocation["ClientStatus"] != "running"
        or task.get("State") != "running"
    ):
        raise RuntimeError("The service is not running.")
    return allocation


def register_volumes(client, saved, path):
    nodes = [
        node
        for node in experiment.request(client, "GET", "nodes").json()
        if node["Status"] == "ready"
        and node.get("Drivers", {}).get("docker", {}).get("Healthy")
    ]
    if len(nodes) != 1:
        raise RuntimeError("Require one ready Docker-capable Nomad client.")
    for name in ("delivery", "data"):
        volume = {
            "Name": f"{saved['job_id']}-{name}",
            "Namespace": "default",
            "NodeID": nodes[0]["ID"],
            "HostPath": str(path.parent / name),
            "RequestedCapabilities": [
                {
                    "AccessMode": "single-node-reader-only"
                    if name == "delivery"
                    else "single-node-writer",
                    "AttachmentMode": "file-system",
                }
            ],
        }
        value = experiment.request(
            client, "PUT", "volume/host/register", json={"Volume": volume}
        ).json()["Volume"]
        saved["volume_ids"][name] = value["ID"]
        experiment.save_json(path, saved)


def docker_delivery(saved):
    def docker(*args):
        return subprocess.run(
            ["docker", *args], capture_output=True, text=True, check=True, timeout=15
        ).stdout

    identifiers = docker(
        "ps",
        "--filter",
        f"label=com.hashicorp.nomad.alloc_id={saved['allocation_id']}",
        "--format",
        "{{.ID}}",
    ).split()
    if len(identifiers) != 1:
        raise RuntimeError(
            "Cannot identify exactly one Docker container for the service allocation."
        )
    container = identifiers[0]
    (info,) = json.loads(docker("inspect", container))
    mounts = {mount["Destination"]: mount for mount in info.get("Mounts", [])}
    if (
        mounts.get("/delivery", {}).get("RW") is not False
        or mounts.get("/data", {}).get("RW") is not True
    ):
        raise RuntimeError("The service mounts have incorrect write permissions.")
    checksum = docker(
        "exec", container, "sha256sum", "/delivery/maintain-mode.sh"
    ).split()
    if not checksum or checksum[0] != saved["artifact"]["sha256"]:
        raise RuntimeError(
            "The script visible to the service differs from the Harness artifact."
        )
    return {
        "container_id": container,
        "script_sha256": checksum[0],
        "delivery_read_only": True,
        "data_writable": True,
        "mounts": [mounts["/delivery"], mounts["/data"]],
    }


def submit(client, worker, worker_path, saved, path, timeout=30):
    if saved["phase"] != "checkpoint":
        raise ValueError(
            "Submission already started. Observe the existing job or clean it up."
        )
    verify_handoff(worker, worker_path)
    payload = validate_checkpoint(saved)
    sample_files(saved, path.parent / "data", time.monotonic())
    if any(
        (path.parent / "data" / name).stat().st_mode & 0o777 != 0o644
        for name in saved["files"]
    ):
        raise ValueError("Both disposable files must start at 0644.")
    if experiment.retained_job(client, saved) is not None:
        raise ValueError("A job already owns this service ID.")
    saved["phase"] = "submitting"
    experiment.save_json(path, saved)
    register_volumes(client, saved, path)
    experiment.request(
        client,
        "POST",
        "jobs",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    deadline = time.monotonic() + timeout
    while True:
        placed = experiment.allocations(client, saved)
        if len(placed) > 1:
            raise RuntimeError("Nomad placed more than one service allocation.")
        if placed:
            allocation = experiment.request(
                client, "GET", f"allocation/{placed[0]['ID']}"
            ).json()
            saved["allocation_id"] = allocation["ID"]
            experiment.save_json(path, saved)
            if allocation["ClientStatus"] in TERMINAL:
                raise RuntimeError("The service exited before observation.")
            if (
                allocation["ClientStatus"] == "running"
                and (allocation.get("TaskStates") or {}).get("service", {}).get("State")
                == "running"
            ):
                break
        if time.monotonic() >= deadline:
            raise RuntimeError("The service did not start before the bounded deadline.")
        time.sleep(SAMPLE_SECONDS)
    current_allocation(client, saved)
    experiment.save_json(path.parent / "allocation.json", allocation)
    saved["deployment"] = docker_delivery(saved)
    saved["phase"] = "running"
    experiment.save_json(path, saved)
    return saved


def sample_files(saved, data, started):
    sample = {"at": datetime.now(UTC).isoformat()}
    for name, expected in saved["files"].items():
        file = data / name
        mode = f"{file.stat().st_mode & 0o7777:04o}"
        actual = digest(file)
        sample[name] = {"mode": mode, "sha256": actual}
        if actual != expected["sha256"]:
            raise RuntimeError(f"The service changed {name} contents.")
        if name == "sibling" and mode != "0644":
            raise RuntimeError("The service changed the sibling mode.")
    sample["elapsed_seconds"] = time.monotonic() - started
    return sample


def observe_mode(saved, data, stage, deadline, check, persist, *, hold=False):
    result = {"deadline_seconds": deadline, "samples": [], "passed": False}
    saved["observations"][stage] = result
    persist()
    started = time.monotonic()
    try:
        if stage in ("drift", "shutdown"):
            (data / "target").chmod(0o644)
        while True:
            check()
            sample = sample_files(saved, data, started)
            result["samples"].append(sample)
            result["elapsed_seconds"] = sample["elapsed_seconds"]
            persist()
            mode = sample["target"]["mode"]
            if hold:
                if mode != "0644":
                    raise RuntimeError("The stopped service corrected the target.")
                if sample["elapsed_seconds"] >= deadline:
                    break
            elif mode == "0600" and sample["elapsed_seconds"] <= deadline:
                break
            elif sample["elapsed_seconds"] >= deadline:
                raise RuntimeError(f"{stage} correction missed its deadline.")
            time.sleep(SAMPLE_SECONDS)
        result["passed"] = True
    except (RuntimeError, OSError, httpx.HTTPError) as error:
        result["error"] = str(error)
        raise
    finally:
        persist()
    return result


def observe(client, saved, path):
    if saved["phase"] == "drift_observed":
        return saved
    if saved["phase"] != "running":
        raise ValueError("Submit the service before observation.")
    if saved["observations"]:
        raise ValueError(
            "Observation was interrupted. Clean up this service before a fresh experiment."
        )
    persist = lambda: experiment.save_json(path, saved)
    check = lambda: current_allocation(client, saved)
    data = path.parent / "data"
    observe_mode(saved, data, "startup", STARTUP_SECONDS, check, persist)
    observe_mode(saved, data, "drift", CORRECTION_SECONDS, check, persist)
    saved["phase"] = "drift_observed"
    persist()
    return saved


def stop_allocations(client, saved, path):
    if experiment.retained_job(client, saved) is None:
        return
    experiment.request(client, "DELETE", f"job/{saved['job_id']}?purge=false")
    deadline = time.monotonic() + 30
    while True:
        placed = experiment.allocations(client, saved)
        if all(allocation["ClientStatus"] in TERMINAL for allocation in placed):
            saved["stopped_allocations"] = placed
            experiment.save_json(path, saved)
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("The service did not stop within 30 seconds.")
        time.sleep(SAMPLE_SECONDS)


def remove_volumes(client, saved, path):
    # Discover a registration whose response was lost before its ID was saved.
    listed = (
        experiment.request(client, "GET", "volumes", params={"type": "host"}).json()
        or []
    )
    for name in ("delivery", "data"):
        identifiers = {
            entry["ID"]
            for entry in listed
            if entry.get("Name") == f"{saved['job_id']}-{name}"
        }
        if saved["volume_ids"].get(name):
            identifiers.add(saved["volume_ids"][name])
        for identifier in identifiers:
            response = client.get(f"volume/host/{identifier}")
            if response.status_code == 404:
                continue
            response.raise_for_status()
            volume = response.json()
            if volume.get("HostPath") != str(path.parent / name):
                raise RuntimeError("Refusing to remove another experiment's volume.")
            experiment.request(client, "DELETE", f"volume/host/{identifier}/delete")


def cleanup(client, saved, path):
    saved["cleanup_pending"] = True
    experiment.save_json(path, saved)
    stop_allocations(client, saved, path)
    if experiment.retained_job(client, saved) is not None:
        for allocation in experiment.allocations(client, saved):
            for stream in ("stdout", "stderr"):
                response = client.get(
                    f"client/fs/logs/{allocation['ID']}",
                    params={"task": "service", "type": stream, "plain": "true"},
                )
                if response.is_success:
                    (path.parent / f"{stream}.log").write_bytes(response.content)
            experiment.request(
                client, "GET", f"client/allocation/{allocation['ID']}/gc"
            )
        experiment.request(client, "DELETE", f"job/{saved['job_id']}?purge=true")
    if experiment.retained_job(client, saved) is not None:
        raise RuntimeError("The service job survived cleanup.")
    remove_volumes(client, saved, path)
    remove_staging(path)
    saved.update(
        cleanup_pending=False,
        cleanup={
            "job_removed": True,
            "volumes_removed": True,
            "directories_removed": True,
        },
    )
    experiment.save_json(path, saved)


def stop(client, worker, worker_path, saved, path):
    if saved["phase"] == "finished":
        return saved
    if saved["phase"] not in ("drift_observed", "stopping"):
        raise ValueError(
            "Require startup and drift observations before shutdown acceptance."
        )
    saved["phase"] = "stopping"
    experiment.save_json(path, saved)
    stop_allocations(client, saved, path)
    observe_mode(
        saved,
        path.parent / "data",
        "shutdown",
        SHUTDOWN_SECONDS,
        lambda: current_allocation(client, saved, stopped=True),
        lambda: experiment.save_json(path, saved),
        hold=True,
    )
    inspection = verify_handoff(worker, worker_path)
    experiment.save_json(path.parent / "after-service-attempt.json", inspection)
    artifact = experiment.export_artifact(
        worker,
        path.parent / "after-service-maintain-mode.sh",
        saved["artifact"]["sha256"],
        saved["artifact"]["id"],
    )
    if artifact != saved["artifact"]:
        raise RuntimeError("The saved artifact metadata changed.")
    cleanup(client, saved, path)
    saved.update(phase="finished", verified=True)
    experiment.save_json(path, saved)
    return saved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "step", choices=("checkpoint", "submit", "observe", "stop", "cleanup")
    )
    parser.add_argument(
        "--receipt", type=Path, required=True, help="The existing worker receipt."
    )
    parser.add_argument("--image", default=SHELL_IMAGE)
    parser.add_argument("--nomad-addr", default="http://127.0.0.1:14646")
    args = parser.parse_args()
    worker_path = args.receipt.resolve()
    try:
        with worker_path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            worker = json.loads(worker_path.read_text())
            path = service_path(worker_path)
            if args.step == "checkpoint":
                result = checkpoint(worker, worker_path, args.image)
            else:
                saved = json.loads(path.read_text())
                allowed = {
                    "submit": {"checkpoint"},
                    "observe": {"running", "drift_observed"},
                    "stop": {"drift_observed", "stopping", "finished"},
                }
                if args.step in allowed and saved["phase"] not in allowed[args.step]:
                    raise ValueError(
                        "This receipt is not ready for that step. Inspect or clean it up."
                    )
                if saved["nomad_address"] and saved["nomad_address"] != args.nomad_addr:
                    raise ValueError("Use the original Nomad destination.")
                saved["nomad_address"] = args.nomad_addr
                headers = (
                    {"X-Nomad-Token": os.environ["NOMAD_TOKEN"]}
                    if os.environ.get("NOMAD_TOKEN")
                    else {}
                )
                with httpx.Client(
                    base_url=args.nomad_addr.rstrip("/") + "/v1/",
                    headers=headers,
                    timeout=5,
                    trust_env=False,
                ) as client:
                    try:
                        if args.step == "submit":
                            result = submit(client, worker, worker_path, saved, path)
                        elif args.step == "observe":
                            result = observe(client, saved, path)
                        elif args.step == "stop":
                            result = stop(client, worker, worker_path, saved, path)
                        else:
                            cleanup(client, saved, path)
                            if saved["phase"] != "finished":
                                saved["phase"] = "aborted"
                            experiment.save_json(path, saved)
                            result = saved
                    except (
                        ValueError,
                        RuntimeError,
                        OSError,
                        subprocess.SubprocessError,
                        httpx.HTTPError,
                    ) as error:
                        saved.update(error=str(error), verified=False)
                        try:
                            cleanup(client, saved, path)
                            saved["phase"] = "failed"
                        except (
                            ValueError,
                            RuntimeError,
                            OSError,
                            subprocess.SubprocessError,
                            httpx.HTTPError,
                        ) as cleanup_error:
                            saved["cleanup_error"] = str(cleanup_error)
                        experiment.save_json(path, saved)
                        raise
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (
        ValueError,
        RuntimeError,
        OSError,
        subprocess.SubprocessError,
        httpx.HTTPError,
    ) as error:
        print(f"standing: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
