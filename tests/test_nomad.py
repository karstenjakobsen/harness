import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from harness.evidence import Run
from harness.nomad_backend import NomadBackend, batch_job


class NomadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.run = Run.create(Path(directory.name), "codex", "worker:local", "worker-net", "nomad")

    def test_auth_is_a_read_only_client_volume(self):
        with patch.dict("os.environ", CODEX_AUTH_FILE="/some/host/auth.json"):
            job = batch_job(self.run.read(), "run-token")
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
            NomadBackend.terminal_state(self.run, alloc)

    async def test_restart_reuses_existing_job(self):
        backend = NomadBackend("http://nomad")
        await backend.close()
        requests = []

        def reply(request):
            requests.append(request.method)
            return httpx.Response(200, json={"Meta": {"harness_run": self.run.path.name}})

        backend.api = httpx.AsyncClient(
            base_url="http://nomad", transport=httpx.MockTransport(reply)
        )
        self.addAsyncCleanup(backend.close)
        await backend.register(self.run, "run-token")
        self.assertEqual(requests, ["GET"])
        self.assertEqual(self.run.read()["job_id"], "harness-" + self.run.path.name)

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
        with patch.dict("os.environ", CODEX_AUTH_FILE="/some/host/auth.json"):
            await backend.ensure_registered(self.run, "run-token")
        self.assertEqual(submitted, 1)
        self.assertEqual(job["ID"], self.run.read()["job_id"])
