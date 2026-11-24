import tempfile
import unittest
from pathlib import Path

from harness.evidence import EXPECTED, Run


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.run = Run.create(self.root, "codex", "image", "network")

    def finish(self, code=0):
        self.run.finish({"ExitCode": code, "StartedAt": "start", "FinishedAt": "end"}, False)
        return self.run.read(trace=True)

    def write_and_read(self):
        self.run.file_tool("write_file", "result.txt", EXPECTED)
        self.run.file_tool("read_file", "result.txt")

    def test_worker_report_cannot_override_disk(self):
        self.write_and_read()
        self.run.file.write_bytes(EXPECTED.encode() + b"\n")
        record = self.finish()
        self.assertEqual(record["status"], "verification failed")
        self.assertTrue(record["verification"]["observed_write_then_read"])
        self.assertFalse(record["verification"]["exact_bytes"])

    def test_read_back_is_required(self):
        self.run.file_tool("write_file", "result.txt", EXPECTED)
        self.assertEqual(self.finish()["status"], "verification failed")

    def test_nonzero_exit_with_correct_output(self):
        self.write_and_read()
        self.assertEqual(self.finish(7)["status"], "worker failed")

    def test_workspace_and_lookup_scope(self):
        with self.assertRaises(ValueError):
            self.run.file_tool("write_file", "../run.json", "overwrite")
        self.assertIn("error", self.run.read(True)["tool_calls"][0])
        with self.assertRaises(ValueError):
            Run(self.root, "../../outside")
