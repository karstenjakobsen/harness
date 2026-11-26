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
                self.reply(200, allocations[0])
            elif path.endswith("/allocations"):
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
