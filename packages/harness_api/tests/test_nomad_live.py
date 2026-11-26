import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import monotonic, sleep
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

from harness_api import NomadBackend, WorkloadSpec

pytestmark = pytest.mark.nomad
IMAGE = "docker.io/library/busybox@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec"


def api(address, path, *, method="GET", body=None):
    request = Request(
        f"{address}/v1/{path}",
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=5) as response:
        return response.read()


def jobs_for_run(address, run_id):
    jobs = json.loads(api(address, "jobs?prefix=harness-&meta=true")) or []
    return [
        job["ID"]
        for job in jobs
        if (job.get("Meta") or {}).get("harness_run_id") == run_id
    ]


@pytest.fixture
def run():
    if "HARNESS_NOMAD_ADDR" not in os.environ:
        pytest.skip("use make test-nomad to start the local cluster")
    address = os.environ["HARNESS_NOMAD_ADDR"]
    run_id = str(uuid4())
    try:
        yield address, run_id, NomadBackend(address)
    finally:
        for job_id in jobs_for_run(address, run_id):
            api(address, f"job/{job_id}?purge=true", method="DELETE")


def wait_for(backend, handle, state):
    deadline = monotonic() + 90
    while True:
        status = backend.inspect(handle)
        if status.state == state:
            return status
        if (
            status.state in ("succeeded", "failed", "stopped")
            or monotonic() >= deadline
        ):
            pytest.fail(f"Expected {state}, observed {status}")
        sleep(0.3)


def verify_one_task(address, run_id, status):
    assert jobs_for_run(address, run_id) == [status.job_id]
    allocations = json.loads(api(address, f"job/{status.job_id}/allocations?all=true"))
    assert [a["ID"] for a in allocations] == [status.allocation_id]
    alloc = json.loads(api(address, f"allocation/{status.allocation_id}"))
    restarts = alloc["TaskStates"]["workload"]["Restarts"]
    print(f"{status} allocations={len(allocations)} restarts={restarts}")
    assert restarts == 0


@pytest.mark.parametrize(("code", "state"), [(0, "succeeded"), (7, "failed")])
def test_batch_exit(run, code, state):
    address, run_id, backend = run
    marker = f"slice9-{run_id}"
    spec = WorkloadSpec(
        IMAGE, ("sh", "-c", 'echo "$1"; exit "$2"', "workload", marker, str(code))
    )
    handle = backend.start(run_id, spec)
    status = wait_for(backend, handle, state)
    assert status.job_id == handle and status.exit_code == code
    verify_one_task(address, run_id, status)
    if code == 0:
        path = f"client/fs/logs/{status.allocation_id}?task=workload&type=stdout&plain=true"
        output = api(address, path).decode().strip()
        assert output == marker
        print(f"stdout={output} image={IMAGE}")


def test_concurrent_start_and_repeated_stop(run):
    address, run_id, backend = run
    spec = WorkloadSpec(IMAGE, ("sleep", "300"))
    barrier = Barrier(2, timeout=10)

    def start():
        barrier.wait()
        return backend.start(run_id, spec)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(start) for _ in range(2)]
        first, second = [future.result() for future in futures]
    print(f"concurrent handles: {first} {second}")
    assert first == second
    running = wait_for(backend, first, "running")
    assert running.allocation_id
    backend.stop(first)
    backend.stop(second)
    stopped = wait_for(backend, first, "stopped")
    assert stopped.allocation_id == running.allocation_id
    verify_one_task(address, run_id, stopped)


def test_literal_argument_vector(run):
    address, run_id, backend = run
    values = (
        "${NOMAD_ALLOC_ID}",
        "prefix-${NOMAD_JOB_ID}",
        "$${NOMAD_ALLOC_ID}",
        "%{if true}",
        "",
        "two words",
    )
    handle = backend.start(run_id, WorkloadSpec(IMAGE, ("printf", "%s\\n", *values)))
    status = wait_for(backend, handle, "succeeded")
    path = f"client/fs/logs/{status.allocation_id}?task=workload&type=stdout&plain=true"
    assert api(address, path).decode().splitlines() == list(values)
    print(
        f"Verified literal argv including {values[0]} on allocation {status.allocation_id}"
    )


def test_additional_allocation_cannot_start_the_workload(run):
    address, run_id, backend = run
    handle = backend.start(run_id, WorkloadSpec(IMAGE, ("sleep", "300")))
    original = wait_for(backend, handle, "running")
    # Request another placement directly at Nomad to bypass the one-allocation policy.
    api(
        address,
        f"job/{handle}/scale",
        method="POST",
        body={"Count": 2, "Target": {"Group": "workload"}},
    )
    deadline = monotonic() + 45
    while monotonic() < deadline:
        status = backend.inspect(handle)
        if status.replacement_allocation_ids:
            assert status.state == "unknown" and status.exit_code is None
            assert status.allocation_id == original.allocation_id
            (successor,) = status.replacement_allocation_ids
            alloc = json.loads(api(address, f"allocation/{successor}"))
            if alloc["ClientStatus"] == "failed":
                guard = alloc["TaskStates"]["guard"]
                assert any(
                    event["Type"] == "Terminated" and event["ExitCode"] == 1
                    for event in guard["Events"]
                )
                assert not any(
                    event["Type"] == "Started"
                    for event in alloc["TaskStates"]["workload"]["Events"]
                )
                message = api(
                    address,
                    f"client/fs/logs/{successor}?task=guard&type=stderr&plain=true",
                )
                assert b"Refusing to launch" in message
                print(f"{status} additional workload starts=0")
                return
        sleep(0.3)
    pytest.fail(
        f"Expected the replacement to be refused before workload startup, observed {status}"
    )


@pytest.mark.skipif(
    "HARNESS_NOMAD_TEST_CLIENT_UNIT" not in os.environ,
    reason="heartbeat loss is exercised on the evidence script's disposable client",
)
def test_client_disconnect_and_reconnect(run):
    address, run_id, backend = run
    unit = os.environ["HARNESS_NOMAD_TEST_CLIENT_UNIT"]
    handle = backend.start(run_id, WorkloadSpec(IMAGE, ("sleep", "300")))
    running = wait_for(backend, handle, "running")
    alloc = json.loads(api(address, f"allocation/{running.allocation_id}"))
    node = json.loads(api(address, f"node/{alloc['NodeID']}"))
    assert node["Name"].startswith("harness-nomad-") and node["Name"].endswith(
        "-client"
    )
    key = node["Name"].removeprefix("harness-nomad-").removesuffix("-client")
    assert unit == f"harness-nomad-client@{key}.service"
    signal_agent = ["systemctl", "--user", "kill", "--kill-whom=main"]
    try:
        subprocess.run([*signal_agent, "--signal=STOP", unit], check=True)
        uncertain = wait_for(backend, handle, "unknown")
        assert uncertain.allocation_id == running.allocation_id
        assert uncertain.exit_code is None and not uncertain.replacement_allocation_ids
        print(f"Missed client heartbeats: {uncertain}")
    finally:
        subprocess.run([*signal_agent, "--signal=CONT", unit], check=True)
    resumed = wait_for(backend, handle, "running")
    assert resumed.allocation_id == running.allocation_id
    verify_one_task(address, run_id, resumed)
    backend.stop(handle)
    wait_for(backend, handle, "stopped")
