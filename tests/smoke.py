"""Drive the actual Compose operator CLI and look up each trace after worker removal."""

import json
import re
import subprocess
import time
from datetime import datetime
from unittest import TestCase

operator = ["docker", "compose", "run", "--rm", "--no-deps", "-T", "operator"]
check = TestCase()


def check_run(worker: str, status: str, actual: str | None):
    result = subprocess.run(
        [*operator, "run", "--worker", worker], stdout=subprocess.PIPE, text=True
    )
    print(result.stdout, end="", flush=True)
    match = re.search(r"^run_id=([0-9a-f-]{36})$", result.stdout, re.MULTILINE)
    check.assertIsNotNone(match, result.stdout)
    check.assertEqual(result.returncode, int(status != "passed"))
    deadline = time.monotonic() + 15
    while True:
        trace = json.loads(subprocess.check_output([*operator, "get", match[1]]))
        if trace.get("cleanup") != "pending" or time.monotonic() > deadline:
            break
        time.sleep(0.5)
    check.assertEqual(trace["status"], status, trace.get("error"))
    check.assertEqual(trace["cleanup"], "removed")
    check.assertEqual(trace["run_id"], match[1])
    check.assertRegex(trace["container_id"], r"^[0-9a-f]{64}$")
    check.assertEqual(trace["exit_code"], 0)
    check.assertEqual(trace["verification"]["actual"], actual)
    check.assertEqual(trace["verification"]["exact_bytes"], status == "passed")
    check.assertLessEqual(
        datetime.fromisoformat(trace["exited_at"]),
        datetime.fromisoformat(trace["verification"]["checked_at"]),
    )
    check.assertTrue(trace["worker_stdout"])
    tools = [event["tool"] for event in trace["tool_calls"]]
    check.assertEqual(tools, ["write_file", "read_file"] if actual is not None else [])


if __name__ == "__main__":
    check_run("fixture-write", "passed", "hello from the harness")
    check_run("fixture-missing", "verification failed", None)
    check_run("fixture-wrong", "verification failed", "hello from the harness\n")
