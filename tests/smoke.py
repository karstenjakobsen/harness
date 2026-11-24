"""Drive the actual Compose operator CLI and look up each trace after worker removal."""

import json
import os
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
    if os.getenv("BACKEND") == "nomad":
        check.assertEqual(trace["backend"], "nomad")
        check.assertEqual(trace["job_id"], "harness-" + match[1])
        check.assertRegex(trace["allocation_id"], r"^[0-9a-f-]{36}$")
        check.assertEqual(trace["allocation_status"], "complete")
    else:
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
    return trace


if __name__ == "__main__":
    traces = [
        check_run("fixture-write", "passed", "hello from the harness"),
        check_run("fixture-missing", "verification failed", None),
        check_run("fixture-wrong", "verification failed", "hello from the harness\n"),
    ]
    if os.getenv("BACKEND") == "nomad":
        # Ask the scheduler independently of the harness cleanup field.
        paths = [
            path
            for trace in traces
            for path in [
                f"/v1/job/{trace['job_id']}",
                f"/v1/client/fs/ls/{trace['allocation_id']}",
            ]
        ]
        probe = (
            "import httpx, json, os, sys; "
            "print(json.dumps([httpx.get(os.environ['NOMAD_ADDR'] + p).status_code "
            "for p in sys.argv[1:]]))"
        )
        statuses = subprocess.check_output(
            ["docker", "compose", "exec", "-T", "harness", "python", "-c", probe, *paths]
        )
        check.assertEqual(json.loads(statuses), [404] * len(paths))
        subprocess.run(["docker", "compose", "restart", "harness"], check=True)
        for original in traces:
            recovered = subprocess.check_output(
                ["make", "-s", "--no-print-directory", "get", f"RUN_ID={original['run_id']}"]
            )
            check.assertEqual(json.loads(recovered), original)
        print("All three traces matched after allocation cleanup and harness restart.")
