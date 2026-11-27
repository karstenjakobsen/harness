#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
make check
make test
workspace=${SLICE13_WORKSPACE:-}
if [[ -z $workspace ]]; then
  mkdir -p .harness/phase2
  log=$(mktemp "$PWD/.harness/phase2/slice13-live-XXXXXX.log")
  make test-phase2-watch > "$log" 2>&1
  workspace=$(sed -n 's/^Slice 13 workspace saved under //p' "$log" | tail -1)
fi
.venv/bin/python - "$workspace" <<'PY'
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path("dev/phase2").resolve()))
import watch

workspace = Path(sys.argv[1]).resolve()
receipt = json.loads((workspace / "phase2/receipt.json").read_text())
attempt = receipt["attempt_id"]
outcome = receipt["execution"]
assert receipt["mode"] == "worker" and receipt["phase"] == "finished"
assert outcome["worker_sessions"] == 1 and outcome["ai_operator_sessions"] == 0
assert all(command[0] != "ask" for command in receipt["owner_commands"])
assert outcome.get("observer_error") is None

# Replay by attempt ID after the allocation, scratch and runtime are gone.
headers = {"X-Nomad-Token": os.environ["NOMAD_TOKEN"]} if os.environ.get("NOMAD_TOKEN") else {}
with httpx.Client(base_url=receipt["nomad_address"].rstrip("/") + "/v1/", headers=headers, timeout=5, trust_env=False) as client:
    assert client.get(f"job/{receipt['job_id']}").status_code == 404
    allocation = client.get(f"allocation/{outcome['allocation_id']}")
    print(f"Nomad after cleanup: job 404, allocation {allocation.status_code}")
assert not (workspace / "phase2/scratch").exists() and not (workspace / "phase2/runtime").exists()
replayed = watch.replay(workspace, attempt)
assert (replayed["job_id"], replayed["allocation_id"], replayed["task"]) == (receipt["job_id"], outcome["allocation_id"], "workload")
assert replayed["capture_status"] == "complete" and not replayed["partial_last_line"]

live = replayed["live_event"]
assert live["summary"]["kind"] in watch.SUBSTANTIVE and live["running_confirmed"]
assert replayed["live_event_located"] == {"line": live["line"], "sha256": live["sha256"]}
(running,) = [o for o in json.loads((watch.activity_directory(workspace, attempt) / "capture.json").read_text())["running_observations"] if o["line"] == live["line"]]
assert (running["client_status"], running["task_state"]) == ("running", "running")
assert datetime.fromisoformat(running["observed_at"]) >= datetime.fromisoformat(live["displayed_at"])

task = replayed["task_outcome"]
assert task["task_state"] == "dead" and task["exit_code"] == outcome["exit_code"]
assert task["restarts"] == 0
assert datetime.fromisoformat(running["observed_at"]) < datetime.fromisoformat(task["finished_at"][:26] + "+00:00")

# Recheck the claimed submission against the worker MCP audit now.
events, _ = watch.read_events(watch.activity_directory(workspace, attempt) / "stdout.jsonl")
submission = watch.submission_check(receipt, events)
assert submission["consistent"]
if submission["claimed_success"]:
    assert submission["artifact"]["id"] == outcome["artifact_id"]
    assert submission["artifact"]["attempt_id"] == attempt

directory = watch.activity_directory(workspace, attempt)
for name in ("stdout.jsonl", "stderr.log"):
    assert (directory / name).stat().st_mode & 0o077 == 0
assert "Bearer" not in (directory / "capture.json").read_text()

print("Slice 13 acceptance verified from the retained capture, Nomad and a fresh owner CLI read")
print(json.dumps({
    "workspace": str(workspace), "attempt_id": attempt, "job_id": receipt["job_id"],
    "allocation_id": outcome["allocation_id"], "task": "workload", "image": receipt["image"],
    "capture_status": replayed["capture_status"], "stdout_events": replayed["events"],
    "stderr_bytes": (directory / "stderr.log").stat().st_size,
    "live_event": live, "running_observation": running, "task_outcome": task,
    "worker_outcome": replayed["worker_outcome"], "submission": submission,
}, ensure_ascii=False, indent=2))
print("Sanitized replay excerpt (selected fields only)")
for number, event, _ in events:
    selected = watch.summary(event)
    if selected and event["type"] == "item.completed":
        print(json.dumps({"line": number, **selected}, ensure_ascii=False))
PY
git diff --check
