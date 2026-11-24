import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from harness.engine import Engine
from harness.evidence import Run, Workspace
from harness.hello_file import EXPECTED, FileOutcome
from harness.launch import WorkerExit


class EvidenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.enterContext(
            patch.dict(os.environ, WORKER_IMAGE="image", WORKER_NETWORK="network", NOMAD_ADDR="")
        )
        self.enterContext(patch("harness.docker_backend.docker.from_env"))
        self.engine = Engine(self.root, "key")
        self.engine.backend = AsyncMock()
        self.engine.backend.name = "docker"
        self.engine.backend.logs.return_value = b""
        with patch.object(self.engine, "watch"):
            run_id = self.engine.submit(FileOutcome(), "fixture-write")
        self.run = Run(self.root, run_id)
        self.workspace = Workspace(self.run.workspace, self.run.calls, FileOutcome().files)

    async def finish(self, code=0):
        self.engine.backend.wait.return_value = WorkerExit(code, "start", "end")
        await self.engine.execute(self.run, "token")
        return self.engine.get_run(self.run.path.name, True)

    def write_and_read(self):
        self.workspace.file_tool("write_file", "result.txt", EXPECTED)
        self.workspace.file_tool("read_file", "result.txt")

    async def test_worker_report_cannot_override_disk(self):
        self.write_and_read()
        (self.run.workspace / "result.txt").write_bytes(EXPECTED.encode() + b"\n")
        record = await self.finish()
        self.assertEqual(record["status"], "verification failed")
        self.assertEqual(record["execution_status"], "succeeded")
        self.assertEqual(record["verification_status"], "failed")
        self.assertTrue(record["verification"]["observed_write_then_read"])
        self.assertFalse(record["verification"]["exact_bytes"])

    async def test_read_back_is_required(self):
        self.workspace.file_tool("write_file", "result.txt", EXPECTED)
        self.assertEqual((await self.finish())["status"], "verification failed")

    async def test_nonzero_exit_with_correct_output(self):
        self.write_and_read()
        record = await self.finish(7)
        self.assertEqual(record["status"], "worker failed")
        self.assertEqual(record["execution_status"], "failed")
        self.assertEqual(record["verification_status"], "passed")

    async def test_resume_after_exit_verifies_without_relaunching(self):
        self.write_and_read()
        self.run.exited(WorkerExit(0, "start", "end"))
        await self.engine.execute(self.run, "token")
        self.engine.backend.wait.assert_not_awaited()
        self.engine.backend.cleanup.assert_awaited_once()
        self.assertEqual(self.run.read()["verification_status"], "passed")

    def test_workspace_and_lookup_scope(self):
        with self.assertRaises(ValueError):
            self.workspace.file_tool("write_file", "../run.json", "overwrite")
        self.assertIn("error", self.run.read(True)["tool_calls"][0])
        with self.assertRaises(ValueError):
            Run(self.root, "../../outside")

    def test_legacy_lookup_preserves_stored_record(self):
        data = self.run.read()
        for field in ("execution_status", "verification_status", "outcome"):
            del data[field]
        data.update(
            task="an earlier prompt",
            status="verification failed",
            exit_code=0,
            verification={"exact_bytes": False, "observed_write_then_read": False},
        )
        original = json.dumps(data)
        self.run.record.write_text(original)
        record = self.engine.get_run(data["run_id"], True)
        self.assertEqual(record["execution_status"], "succeeded")
        self.assertEqual(record["verification_status"], "failed")
        self.assertEqual(self.run.record.read_text(), original)
