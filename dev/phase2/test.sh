#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
mode=${1:-worker}
mkdir -p .harness/phase2
directory=$(mktemp -d "$PWD/.harness/phase2/slice11-XXXXXX")
image=""
seed_options=()
render_options=()
if [[ ${HARNESS_PHASE2_ALLOW_NAMESPACE_OPTIONS:-0} == 1 ]]; then
  render_options+=(--docker-security-opt seccomp=unconfined --docker-security-opt apparmor=unconfined)
fi
if [[ $mode == worker ]]; then
  image=$(docker image inspect --format '{{.Id}}' "${WORKER_IMAGE:-harness-worker:slice10}")
elif [[ $mode == smoke ]]; then
  seed_options+=(--smoke)
else
  echo 'Expected worker or smoke.' >&2
  exit 1
fi

run_case() {
  local name=$1
  shift
  local workspace="$directory/$name"
  .venv/bin/python dev/phase2/experiment.py seed --workspace "$workspace" "${seed_options[@]}" "$@"
  local receipt="$workspace/phase2/receipt.json"
  if [[ $mode == worker ]]; then
    .venv/bin/python dev/phase2/experiment.py render --receipt "$receipt" --image "$image" "${render_options[@]}" --mcp-url "${HARNESS_PHASE2_MCP_URL:-http://127.0.0.1:8001/mcp}"
  else
    .venv/bin/python dev/phase2/experiment.py render --receipt "$receipt"
  fi
  echo 'Rendering checkpoint. The prepared attempt and exact job follow.'
  cat "$workspace/phase2/prepared.json" "$workspace/phase2/job.json"
  if [[ $name == first ]]; then
    local started=$SECONDS
    make nomad-up
    echo "Cluster setup/readiness seconds=$((SECONDS - started))"
  fi
  .venv/bin/python dev/phase2/experiment.py run --receipt "$receipt" --nomad-addr "${HARNESS_NOMAD_ADDR:-http://127.0.0.1:14646}"
  .venv/bin/python - "$receipt" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
receipt = json.loads(path.read_text())
outcome = receipt["execution"]
assert outcome["verified"] and outcome["cleanup"]["scratch_removed"]
filename = path.parent / "evidence" / receipt["fixture"]["filename"]
if outcome["exit_code"] == 0:
    assert hashlib.sha256(filename.read_bytes()).hexdigest() == outcome["file_sha256"]
else:
    assert outcome["exit_code"] == 7 and not filename.exists()
print(json.dumps({"mode": receipt["mode"], "attempt_id": receipt["attempt_id"], "job_id": receipt["job_id"], **outcome}, indent=2))
PY
}

run_case first
if [[ $mode == smoke ]]; then
  run_case second
  .venv/bin/python - "$directory/failure.json" <<'PY'
import json
import sys
from pathlib import Path

fixture = json.loads(Path("dev/phase2/cities.json").read_text())
fixture.update(smoke_argv=["sh", "-c", "exit 7"], smoke_expected_exit_code=7)
Path(sys.argv[1]).write_text(json.dumps(fixture))
PY
  run_case failure --fixture "$directory/failure.json"
fi
echo "Experiment receipts and outputs saved under $directory"
