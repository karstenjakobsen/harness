import json
import unittest

import httpx

from harness.launch import ExecutionRef, LaunchRequest, WorkerExit
from harness.nomad_backend import NomadBackend, batch_job


class NomadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.request = LaunchRequest(
            ExecutionRef("test-id", "harness-test-id", {}),
            "worker:local",
            "worker-net",
            "codex",
            1000,
            1000,
            {"RUN_TOKEN": "run-token"},
            "/some/host/auth.json",
        )
        self.facts = []

    def test_auth_is_a_read_only_client_volume(self):
        job = batch_job(self.request)
        group = job["TaskGroups"][0]
        task = group["Tasks"][0]
        self.assertNotIn("/some/host", json.dumps(job))
        self.assertEqual(job["Type"], "batch")
        self.assertEqual(task["Config"]["args"], ["codex"])
        self.assertTrue(group["Volumes"]["auth"]["ReadOnly"])
        self.assertTrue(task["VolumeMounts"][0]["ReadOnly"])
        self.assertEqual(task["Env"]["RUN_TOKEN"], "run-token")

    def test_failed_placement_cannot_supply_a_zero_exit(self):
        alloc = {"ClientStatus": "failed", "TaskStates": {}}
        with self.assertRaisesRegex(RuntimeError, "did not report a worker exit"):
            NomadBackend.terminal_state(alloc, self.facts.append)

    def test_confirmed_exit_and_nomad_diagnostics_are_reported_separately(self):
        event = {"Type": "Terminated", "Time": 7, "ExitCode": 3, "DisplayMessage": "exit 3"}
        alloc = {
            "ClientStatus": "failed",
            "TaskStates": {
                "worker": {
                    "State": "dead",
                    "StartedAt": "start",
                    "FinishedAt": "end",
                    "Events": [event],
                }
            },
        }
        exit_info = NomadBackend.terminal_state(alloc, self.facts.append)
        self.assertEqual(exit_info, WorkerExit(3, "start", "end"))
        self.assertEqual(self.facts[0].details["allocation_status"], "failed")
        self.assertEqual(self.facts[0].details["task_events"][0]["message"], "exit 3")

    async def test_restart_reuses_existing_job(self):
        backend = NomadBackend("http://nomad")
        await backend.close()
        requests = []

        def reply(request):
            requests.append(request.method)
            return httpx.Response(200, json={"Meta": {"harness_run": self.request.ref.run_id}})

        backend.api = httpx.AsyncClient(
            base_url="http://nomad", transport=httpx.MockTransport(reply)
        )
        self.addAsyncCleanup(backend.close)
        await backend.register(self.request, self.facts.append)
        self.assertEqual(requests, ["GET"])
        self.assertEqual(self.facts[-1].details["job_id"], "harness-" + self.request.ref.run_id)

    async def test_dropped_registration_reply_does_not_launch_again(self):
        job = None
        submitted = 0

        def reply(request):
            nonlocal job, submitted
            if request.method == "POST":
                submitted += 1
                job = json.loads(request.content)["Job"]
                raise httpx.ReadError("dropped reply", request=request)
            return httpx.Response(200, json=job) if job else httpx.Response(404)

        backend = NomadBackend("http://nomad")
        await backend.close()
        backend.api = httpx.AsyncClient(
            base_url="http://nomad", transport=httpx.MockTransport(reply)
        )
        self.addAsyncCleanup(backend.close)
        await backend.ensure_registered(self.request, self.facts.append)
        self.assertEqual(submitted, 1)
        self.assertEqual(job["ID"], self.facts[-1].details["job_id"])
