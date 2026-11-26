import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from harness_api import (
    NomadBackend,
    StartOutcomeUnknown,
    WorkloadConflictError,
    WorkloadSpec,
)

IMAGE = "busybox@sha256:" + "a" * 64
SPEC = WorkloadSpec(IMAGE, ("true",))


@pytest.fixture
def cluster():
    jobs = {}
    requests = []
    allocations = []

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body):
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_POST(self):
            assert self.path == "/v1/jobs"
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            job = body["Job"]
            if job["ID"] in jobs:
                self.reply(500, "job already exists")
                return
            jobs[job["ID"]] = dict(job, Stop=False)
            # Drop the first response after accepting registration.
            self.close_connection = True

        def do_GET(self):
            path = self.path.removeprefix("/v1/")
            if path.startswith("allocation/"):
                self.reply(
                    200, next(a for a in allocations if a["ID"] == path.split("/")[1])
                )
            elif path.partition("?")[0].endswith("/allocations"):
                self.reply(200, allocations)
            else:
                job = jobs.get(path.removeprefix("job/"))
                self.reply(200 if job else 404, job)

        def do_DELETE(self):
            job_id = self.path.removeprefix("/v1/job/").removesuffix("?purge=false")
            jobs[job_id]["Stop"] = True
            self.reply(200, {})

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield (
                NomadBackend(f"http://127.0.0.1:{server.server_port}"),
                jobs,
                requests,
                allocations,
            )
        finally:
            server.shutdown()
            thread.join()


def test_start_recovers_committed_job_and_rejects_changed_spec(cluster):
    backend, jobs, requests, _ = cluster
    handle = backend.start("one", SPEC)
    assert backend.start("one", SPEC) == handle
    with pytest.raises(WorkloadConflictError):
        backend.start("one", WorkloadSpec(IMAGE, ("false",)))
    assert list(jobs) == [handle]
    for request in requests:
        assert request["EnforceIndex"] is True
        assert request["JobModifyIndex"] == 0
    (group,) = jobs[handle]["TaskGroups"]
    assert group["Disconnect"]["Replace"] is False
    assert group["Disconnect"]["LostAfter"] > 0
    assert group["Count"] == 1
    assert group["RestartPolicy"] == {"Attempts": 0, "Mode": "fail"}
    assert group["ReschedulePolicy"] == {"Attempts": 0, "Unlimited": False}
    assert backend.inspect(handle).state == "pending"
    assert backend.inspect(handle).allocation_id is None


def test_task_failure_and_retained_job_after_stop(cluster):
    backend, jobs, _, allocations = cluster
    handle = backend.start("failed", SPEC)
    task = {
        "State": "dead",
        "Failed": True,
        "Events": [{"Type": "Terminated", "ExitCode": 7}],
    }
    allocations.append(
        {
            "CreateIndex": 10,
            "ID": "alloc",
            "DesiredStatus": "run",
            "ClientStatus": "failed",
            "TaskStates": {"workload": task},
        }
    )
    status = backend.inspect(handle)
    assert (status.state, status.allocation_id, status.exit_code) == (
        "failed",
        "alloc",
        7,
    )
    backend.stop(handle)
    backend.stop(handle)
    assert jobs[handle]["Stop"]
    assert backend.start("failed", SPEC) == handle
    assert backend.inspect(handle).state == "failed"
    task["Events"] = [{"Type": "Driver Failure"}]
    assert backend.inspect(handle).exit_code is None


def test_unreachable_cluster_leaves_registration_uncertain():
    # Reserve a fresh local port without listening on it.
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        backend = NomadBackend(f"http://127.0.0.1:{unused.getsockname()[1]}")
        with pytest.raises(StartOutcomeUnknown, match="same run ID"):
            backend.start("one", SPEC)


def test_rejects_floating_image_and_empty_command():
    with pytest.raises(ValueError, match="digest"):
        WorkloadSpec("busybox:latest", ("true",))
    with pytest.raises(ValueError, match="executable"):
        WorkloadSpec(IMAGE, ())


def test_client_loss_and_successful_replacement_stay_uncertain(cluster):
    backend, _, _, allocations = cluster
    handle = backend.start("lost", SPEC)
    original = {"ID": "original", "CreateIndex": 2, "ClientStatus": "lost"}
    replacement = {
        "ID": "replacement",
        "CreateIndex": 3,
        "PreviousAllocation": "original",
        "ClientStatus": "complete",
        "DesiredStatus": "run",
        "TaskStates": {"workload": {"Events": [{"Type": "Terminated", "ExitCode": 0}]}},
    }
    allocations.append(original)
    status = backend.inspect(handle)
    assert (status.state, status.allocation_id, status.exit_code) == (
        "unknown",
        "original",
        None,
    )
    allocations.insert(0, replacement)
    status = backend.inspect(handle)
    assert (status.state, status.allocation_id, status.exit_code) == (
        "unknown",
        "original",
        None,
    )
    assert status.replacement_allocation_ids == ("replacement",)
    # Even if Nomad retains only the linked successor, its exit cannot settle the attempt.
    allocations.remove(original)
    status = backend.inspect(handle)
    assert status.state == "unknown" and status.exit_code is None
    assert status.allocation_id is None
    assert status.replacement_allocation_ids == ("replacement",)


def test_retry_cannot_adopt_a_retained_job_without_the_allocation_guard(cluster):
    backend, jobs, _, _ = cluster
    handle = backend.start("existing", SPEC)
    jobs[handle]["Meta"].pop("harness_execution_version")
    with pytest.raises(WorkloadConflictError):
        backend.start("existing", SPEC)
    assert backend.inspect(handle).state == "pending"
    backend.stop(handle)
    assert jobs[handle]["Stop"]
