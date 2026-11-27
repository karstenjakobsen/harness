#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
mkdir -p .harness/phase2
evidence_directory=$(mktemp -d "$PWD/.harness/phase2/evidence-XXXXXX")

make check
make test
make test-phase2-smoke > "$evidence_directory/smoke.log" 2>&1

receipt=${SLICE11_RECEIPT:-}
if [[ -z $receipt ]]; then
  make test-phase2 > "$evidence_directory/worker.log" 2>&1
  receipt=$(.venv/bin/python - "$evidence_directory/worker.log" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text()
directory = re.search(r"Experiment receipts and outputs saved under (.+)", text)[1]
print(Path(directory) / "first/phase2/receipt.json")
PY
)
fi

.venv/bin/python - "$receipt" "$evidence_directory" <<'PY'
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

path = Path(sys.argv[1]).resolve()
evidence = Path(sys.argv[2])
receipt = json.loads(path.read_text())
outcome = receipt["execution"]
assert receipt["mode"] == "worker" and outcome["verified"]
assert outcome["allocation_count"] == 1 and outcome["exit_code"] == 0
assert outcome["worker_sessions"] == 1 and outcome["ai_operator_sessions"] == 0
trace = path.parent / "evidence/stdout.log"
events = [json.loads(line) for line in trace.read_text().splitlines() if line.startswith("{")]
assert sum(event.get("type") == "thread.started" for event in events) == 1
assert all(command[0] != "ask" for command in receipt["owner_commands"])
assert not (path.parent / "scratch").exists()
assert not (path.parent / "runtime").exists()

def owner(*args):
    result = subprocess.run([receipt["operator_cli"], *map(str, args)], cwd=receipt["workspace"], capture_output=True, text=True, check=True, timeout=30)
    return json.loads(result.stdout)

inspection = owner("work", "show", receipt["attempt_id"])
for tool in ("get_work_brief", "read_skill", "submit_work_result"):
    assert any(call["tool"] == tool and call["outcome"] == "returned" for call in inspection["calls"])
artifact = owner("work", "artifact", receipt["goal_id"], "--output", evidence / "retrieved-cities.txt")
assert artifact == inspection["artifact"]
assert artifact["attempt_id"] == receipt["attempt_id"]
assert artifact["id"] == outcome["artifact_id"] and artifact["grant_id"] == outcome["grant_id"]
assert artifact["operator_id"] == receipt["operator_id"]
expected = ("\n".join(receipt["fixture"]["cities"]) + "\n").encode()
content = (evidence / "retrieved-cities.txt").read_bytes()
assert content == expected
assert hashlib.sha256(content).hexdigest() == outcome["file_sha256"]
goal = owner("goal", "show", receipt["goal_id"])
assert goal["status"] == "active" and goal["revision"] == receipt["goal_revision"]
print("Required real worker acceptance, verified from retained trace and fresh CLI reads")
print(json.dumps({"receipt": str(path), "goal_id": receipt["goal_id"], "goal_revision": receipt["goal_revision"], "work_item_id": receipt["work_item_id"], "attempt_id": receipt["attempt_id"], "job_id": receipt["job_id"], "image": receipt["image"], **outcome}, indent=2))
print("Retrieved file after worker exit and scratch cleanup")
print(content.decode(), end="")

smoke_directory = Path(re.search(r"Experiment receipts and outputs saved under (.+)", (evidence / "smoke.log").read_text())[1])
print("Optional scheduler smoke results")
for name in ("first", "second", "failure"):
    smoke = json.loads((smoke_directory / name / "phase2/receipt.json").read_text())
    assert smoke["mode"] == "smoke" and smoke["execution"]["verified"]
    print(json.dumps({"case": name, "job_id": smoke["job_id"], **smoke["execution"]}))
print(f"Fresh retrieval and smoke log saved under {evidence}")
PY

git diff --check
