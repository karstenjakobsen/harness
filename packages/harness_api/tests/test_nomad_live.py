import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import monotonic, sleep
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

from harness_api import NomadBackend, WorkloadSpec

pytestmark = pytest.mark.nomad
IMAGE = "docker.io/library/busybox@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec"


def api(address, path, *, method="GET"):
    with urlopen(Request(f"{address}/v1/{path}", method=method), timeout=5) as response:
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
