import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import experiment
import httpx
import pytest


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
        argparse.Namespace(
            image=None, mcp_port=8001, mcp_url=None, docker_security_opt=[]
        ),
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
        argparse.Namespace(
            image=None, mcp_port=8001, mcp_url=None, docker_security_opt=[]
        ),
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
