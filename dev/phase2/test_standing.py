import argparse
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import experiment
import httpx
import pytest
import standing

from harness_api import DATABASE_PATH, WorkAPI


@pytest.fixture
def delivered(tmp_path):
    worker = experiment.seed(
        argparse.Namespace(
            operator=None,
            fixture=standing.DIRECTORY / "file-mode.json",
            smoke=False,
            workspace=tmp_path / "workspace",
            attempt_id=None,
        )
    )
    path = Path(worker["workspace"]) / "phase2/receipt.json"
    scratch = path.parent / "scratch"
    scratch.mkdir()
    api = WorkAPI(Path(worker["workspace"]) / DATABASE_PATH)
    api.set_scratch(worker["attempt_id"], scratch)
    grant = api.grant_attempt(worker["attempt_id"], "fixture-token")
    (scratch / "maintain-mode.sh").write_text(
        '#!/bin/sh\nwhile :; do chmod 0600 "$1"; sleep 0.05; done\n'
    )
    artifact = api.submit_work_result(
        worker["attempt_id"], "fixture-token", "maintain-mode.sh"
    )
    api.revoke_attempt_grant(worker["attempt_id"])
    shutil.rmtree(scratch)
    # A completed worker outcome is a fixture here. Live acceptance requires the
    # actual Nomad allocation and Codex trace through experiment.run instead.
    worker.update(
        phase="finished",
        runtime={"cleaned": True},
        execution={
            "verified": True,
            "exit_code": 0,
            "worker_sessions": 1,
            "ai_operator_sessions": 0,
            "artifact_id": artifact["id"],
            "grant_id": grant["id"],
            "file_sha256": artifact["sha256"],
        },
    )
    experiment.save_json(path, worker)
    return worker, path, api


def test_checkpoint_is_offline_and_preserves_delivery(delivered, monkeypatch):
    worker, path, _ = delivered
    monkeypatch.setenv("HARNESS_NOMAD_ADDR", "http://127.0.0.1:1")
    saved = standing.checkpoint(worker, path, standing.SHELL_IMAGE)
    job = json.loads(Path(saved["job_path"]).read_text())
    (task,) = job["Job"]["TaskGroups"][0]["Tasks"]
    assert saved["job_id"] != worker["job_id"]
    assert saved["phase"] == "checkpoint" and saved["allocation_id"] is None
    assert saved["artifact"]["attempt_id"] == worker["attempt_id"]
    assert standing.digest(Path(saved["script_path"])) == saved["artifact"]["sha256"]
    assert not Path(saved["script_path"]).stat().st_mode & 0o222
    assert task["Config"]["entrypoint"] == ["/bin/sh"]
    assert task["Config"]["args"] == ["/delivery/maintain-mode.sh", "/data/target"]
    assert task["VolumeMounts"] == [
        {"Volume": "delivery", "Destination": "/delivery", "ReadOnly": True},
        {"Volume": "data", "Destination": "/data", "ReadOnly": False},
    ]
    assert "Env" not in task and "security_opt" not in task["Config"]
    assert saved["timing"]["worker_poll_seconds"] == 1
    assert saved["timing"]["correction_deadline_seconds"] == 3
    assert saved["timing"]["shutdown_window_seconds"] == 4
    assert standing.checkpoint(worker, path, standing.SHELL_IMAGE) == saved


def test_seed_records_a_standing_goal_through_the_owner_cli(delivered):
    worker, _, _ = delivered
    goal = experiment.owner_cli(worker, "goal", "show", worker["goal_id"])
    assert goal["duration"] == "standing"
    assert goal["status"] == "active" and goal["revision"] == worker["goal_revision"]


@pytest.mark.parametrize("changed", ["artifact_id", "file_sha256", "goal_revision"])
def test_checkpoint_rejects_different_provenance(delivered, changed):
    worker, path, _ = delivered
    if changed == "goal_revision":
        worker[changed] += 1
    else:
        worker["execution"][changed] = "different"
    with pytest.raises(ValueError, match="provenance"):
        standing.checkpoint(worker, path, standing.SHELL_IMAGE)
    assert not standing.service_path(path).exists()


def test_latest_artifact_from_another_attempt_is_rejected(delivered):
    worker, path, api = delivered
    api.create_attempt("another-attempt", worker["work_item_id"])
    scratch = path.parent / "new-scratch"
    scratch.mkdir()
    api.set_scratch("another-attempt", scratch)
    api.grant_attempt("another-attempt", "other-token")
    (scratch / "maintain-mode.sh").write_text("echo newer\n")
    api.submit_work_result("another-attempt", "other-token", "maintain-mode.sh")
    with pytest.raises(RuntimeError, match="latest artifact"):
        standing.checkpoint(worker, path, standing.SHELL_IMAGE)
    assert not (standing.service_path(path).parent / "delivery").exists()
    assert not (standing.service_path(path).parent / "data").exists()


def test_repeated_checkpoint_rejects_a_different_image(delivered):
    worker, path, _ = delivered
    saved = standing.checkpoint(worker, path, standing.SHELL_IMAGE)
    with pytest.raises(ValueError, match="image"):
        standing.checkpoint(worker, path, "sha256:" + "b" * 64)
    assert json.loads(standing.service_path(path).read_text()) == saved


@pytest.mark.parametrize("changed", ["script_path", "job_path"])
def test_changed_checkpoint_cannot_be_submitted(delivered, changed):
    worker, path, _ = delivered
    saved = standing.checkpoint(worker, path, standing.SHELL_IMAGE)
    target = Path(saved[changed])
    target.chmod(0o644)
    target.write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        standing.validate_checkpoint(saved)


@contextmanager
def local_service(saved, script):
    data = Path(saved["job_path"]).parent / "data"
    process = subprocess.Popen(
        ["/bin/sh", "-c", script, "fixture", str(data / "target")],
        start_new_session=True,
    )
    try:
        yield process, data
    finally:
        try:
            os.killpg(process.pid, 15)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def test_startup_then_drift_then_shutdown_with_real_files(
    delivered, scheduler, monkeypatch
):
    worker, path, _ = delivered
    saved = standing.checkpoint(worker, path, standing.SHELL_IMAGE)
    service_path = standing.service_path(path)
    client, state = scheduler
    state["job"] = {"Meta": saved["metadata"]}
    saved.update(phase="running", allocation_id="service-allocation")
    monkeypatch.setattr(standing, "SHUTDOWN_SECONDS", 0.2)
    with local_service(saved, 'while :; do chmod 0600 "$1"; sleep 0.05; done') as (
        process,
        data,
    ):
        standing.observe(client, saved, service_path)
        assert saved["observations"]["startup"]["passed"]
        assert saved["observations"]["drift"]["passed"]
        assert saved["phase"] == "drift_observed"
        process.terminate()
        process.wait(timeout=5)
        standing.stop(client, worker, path, saved, service_path)
    assert saved["observations"]["shutdown"]["elapsed_seconds"] >= 0.2
    assert saved["observations"]["shutdown"]["passed"]
    assert saved["verified"] and saved["phase"] == "finished"
    assert not data.exists() and state["job"] is None


def test_startup_only_chmod_fails_deliberate_drift(delivered, scheduler, monkeypatch):
    worker, path, _ = delivered
    saved = standing.checkpoint(worker, path, standing.SHELL_IMAGE)
    client, state = scheduler
    state["job"] = {"Meta": saved["metadata"]}
    saved.update(phase="running", allocation_id="service-allocation")
    monkeypatch.setattr(standing, "CORRECTION_SECONDS", 0.2)
    with (
        local_service(saved, 'chmod 0600 "$1"; sleep 30'),
        pytest.raises(RuntimeError, match="drift correction missed"),
    ):
        standing.observe(client, saved, standing.service_path(path))
    assert saved["observations"]["startup"]["passed"]
    assert not saved["observations"]["drift"]["passed"]


@pytest.mark.parametrize(
    "damage", ["sibling-mode", "target-content", "sibling-content"]
)
def test_observer_rejects_unintended_changes(delivered, damage):
    worker, path, _ = delivered
    saved = standing.checkpoint(worker, path, standing.SHELL_IMAGE)
    data = standing.service_path(path).parent / "data"
    if damage == "sibling-mode":
        (data / "sibling").chmod(0o600)
    else:
        (data / damage.split("-")[0]).write_text("corrupted")
    with pytest.raises(RuntimeError, match="changed"):
        standing.observe_mode(saved, data, "startup", 1, lambda: None, lambda: None)


def test_shutdown_rejects_a_still_correcting_service(delivered):
    worker, path, _ = delivered
    saved = standing.checkpoint(worker, path, standing.SHELL_IMAGE)
    with (
        local_service(saved, 'while :; do chmod 0600 "$1"; sleep 0.05; done') as (
            _,
            data,
        ),
        pytest.raises(RuntimeError, match="stopped service corrected"),
    ):
        standing.observe_mode(
            saved, data, "shutdown", 0.3, lambda: None, lambda: None, hold=True
        )


def test_drift_clock_starts_after_recording_the_observation(delivered, monkeypatch):
    worker, path, _ = delivered
    saved = standing.checkpoint(worker, path, standing.SHELL_IMAGE)
    data = standing.service_path(path).parent / "data"
    clock = {"now": 0.0}
    monkeypatch.setattr(standing.time, "monotonic", lambda: clock["now"])

    def persist():
        clock["now"] += 10

    def correct():
        (data / "target").chmod(0o600)

    result = standing.observe_mode(saved, data, "drift", 3, correct, persist)
    assert result["passed"] and result["elapsed_seconds"] == 0


@pytest.fixture
def scheduler():
    state = {"job": None, "posts": 0, "volumes": {}}

    def respond(request):
        route = request.url.path
        if route == "/v1/nodes":
            if state.get("on_nodes"):
                state["on_nodes"]()
            return httpx.Response(
                200,
                json=[
                    {
                        "ID": "node",
                        "Status": "ready",
                        "Drivers": {"docker": {"Healthy": True}},
                    }
                ],
            )
        if route == "/v1/volume/host/register":
            volume = json.loads(request.content)["Volume"]
            volume["ID"] = volume["Name"]
            state["volumes"][volume["ID"]] = volume
            return httpx.Response(200, json={"Volume": volume})
        if route == "/v1/volumes":
            return httpx.Response(200, json=list(state["volumes"].values()))
        if route.startswith("/v1/volume/host/"):
            identifier = route.split("/")[4]
            if request.method == "DELETE":
                del state["volumes"][identifier]
                return httpx.Response(200, json={})
            return httpx.Response(200, json=state["volumes"][identifier])
        if route == "/v1/jobs":
            state["posted_payload"] = request.content
            state["job"] = json.loads(request.content)["Job"]
            state["posts"] += 1
            return httpx.Response(200, json={})
        allocation = {
            "ID": "service-allocation",
            "ClientStatus": "complete" if state.get("stopped") else "running",
            "TaskStates": {"service": {"State": "running", "Restarts": 0}},
        }
        if route.endswith("/allocations"):
            return httpx.Response(200, json=[allocation])
        if route == "/v1/allocation/service-allocation":
            return httpx.Response(200, json=allocation)
        if route.startswith("/v1/job/"):
            if request.method == "DELETE":
                if request.url.params.get("purge") == "true":
                    state["job"] = None
                else:
                    state["stopped"] = True
                    state["job"]["Stop"] = True
                return httpx.Response(200, json={})
            return (
                httpx.Response(200, json=state["job"])
                if state["job"]
                else httpx.Response(404)
            )
        if route.startswith("/v1/client/"):
            return httpx.Response(200, content=b"")
        raise AssertionError(route)

    with httpx.Client(
        base_url="http://nomad.test/v1/", transport=httpx.MockTransport(respond)
    ) as client:
        yield client, state


def test_submission_is_once_and_cleanup_recovers_owned_resources(
    delivered, scheduler, monkeypatch
):
    worker, worker_path, _ = delivered
    saved = standing.checkpoint(worker, worker_path, standing.SHELL_IMAGE)
    path = standing.service_path(worker_path)
    client, state = scheduler
    monkeypatch.setattr(
        standing,
        "docker_delivery",
        lambda saved: {"script_sha256": saved["artifact"]["sha256"]},
    )
    standing.submit(client, worker, worker_path, saved, path)
    with pytest.raises(ValueError, match="Submission already started"):
        standing.submit(client, worker, worker_path, saved, path)
    assert state["posts"] == 1
    assert saved["allocation_id"] == "service-allocation"
    # Recovery reopens persisted ownership, including after a lost registration response.
    saved = json.loads(path.read_text())
    saved["volume_ids"] = {}
    standing.cleanup(client, saved, path)
    assert state["posts"] == 1 and state["job"] is None and state["volumes"] == {}
    assert not (path.parent / "data").exists()
    assert not (path.parent / "delivery").exists()
    assert (path.parent / "attempt.json").exists()


def test_submission_sends_the_validated_job_bytes(delivered, scheduler, monkeypatch):
    worker, worker_path, _ = delivered
    saved = standing.checkpoint(worker, worker_path, standing.SHELL_IMAGE)
    path = standing.service_path(worker_path)
    client, state = scheduler
    job_path = Path(saved["job_path"])
    approved = job_path.read_bytes()

    def change_job():
        job = json.loads(approved)
        job["Job"]["Priority"] = 77
        experiment.save_json(job_path, job)

    state["on_nodes"] = change_job
    monkeypatch.setattr(standing, "docker_delivery", lambda saved: {})
    standing.submit(client, worker, worker_path, saved, path)
    assert state["posted_payload"] == approved
    assert state["posts"] == 1


def test_cleanup_refuses_a_volume_owned_by_another_directory(
    delivered, scheduler, monkeypatch
):
    worker, worker_path, _ = delivered
    saved = standing.checkpoint(worker, worker_path, standing.SHELL_IMAGE)
    path = standing.service_path(worker_path)
    client, state = scheduler
    standing.register_volumes(client, saved, path)
    volume = next(iter(state["volumes"].values()))
    volume["HostPath"] = "/another/experiment"
    with pytest.raises(RuntimeError, match="another experiment"):
        standing.cleanup(client, saved, path)
    assert state["volumes"] and saved["cleanup_pending"]


def test_replacement_allocation_is_rejected(delivered, scheduler):
    worker, worker_path, _ = delivered
    saved = standing.checkpoint(worker, worker_path, standing.SHELL_IMAGE)
    client, state = scheduler
    state["job"] = {"Meta": saved["metadata"]}
    saved["allocation_id"] = "original-allocation"
    with pytest.raises(RuntimeError, match="replaced"):
        standing.current_allocation(client, saved)


def test_cli_rejected_repeat_submission_preserves_completed_receipt(delivered):
    worker, worker_path, _ = delivered
    saved = standing.checkpoint(worker, worker_path, standing.SHELL_IMAGE)
    saved.update(phase="finished", verified=True)
    path = standing.service_path(worker_path)
    experiment.save_json(path, saved)
    result = subprocess.run(
        [
            sys.executable,
            str(standing.DIRECTORY / "standing.py"),
            "submit",
            "--receipt",
            str(worker_path),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 1 and "not ready" in result.stderr
    assert json.loads(path.read_text()) == saved


@pytest.mark.parametrize(
    "visible_hash,read_only",
    [
        ("a" * 64, True),
        ("b" * 64, True),
        ("a" * 64, False),
        ("", True),
        ("a" * 64, None),
    ],
)
def test_container_inspection_checks_visible_bytes_and_mounts(
    tmp_path, monkeypatch, visible_hash, read_only
):
    executable = tmp_path / "docker"
    executable.write_text(
        f"#!{sys.executable}\n"
        + """import json, os, sys
if sys.argv[1] == 'ps':
    print('fixture-container')
elif sys.argv[1] == 'inspect':
    print(os.environ['FIXTURE_DOCKER_INSPECTION'])
elif sys.argv[1] == 'exec':
    if os.environ['FIXTURE_DOCKER_HASH']:
        print(os.environ['FIXTURE_DOCKER_HASH'] + '  /delivery/maintain-mode.sh')
else:
    raise SystemExit(2)
"""
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    mounts = [{"Destination": "/data", "RW": True}]
    if read_only is not None:
        mounts.append({"Destination": "/delivery", "RW": not read_only})
    monkeypatch.setenv(
        "FIXTURE_DOCKER_INSPECTION",
        json.dumps([{"Mounts": mounts}]),
    )
    monkeypatch.setenv("FIXTURE_DOCKER_HASH", visible_hash)
    saved = {"allocation_id": "fixture-allocation", "artifact": {"sha256": "a" * 64}}
    if visible_hash != "a" * 64 or not read_only:
        with pytest.raises(RuntimeError):
            standing.docker_delivery(saved)
    else:
        inspection = standing.docker_delivery(saved)
        assert inspection["script_sha256"] == visible_hash
        assert inspection["delivery_read_only"]
