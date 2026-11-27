#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
mkdir -p .harness/phase2
workspace=$(mktemp -d "$PWD/.harness/phase2/slice12-XXXXXX")
receipt="$workspace/phase2/receipt.json"
nomad_addr=${HARNESS_NOMAD_ADDR:-http://127.0.0.1:14646}
image=$(docker image inspect --format '{{.Id}}' "${WORKER_IMAGE:-harness-worker:slice10}")

recover() {
  local status=$?
  trap - EXIT
  if [[ -f $receipt ]]; then
    if .venv/bin/python - "$receipt" <<'PY'
import json
import sys
from pathlib import Path
sys.exit(json.loads(Path(sys.argv[1]).read_text())["phase"] not in ("running", "observed", "cleanup_pending", "verify_pending"))
PY
    then
      .venv/bin/python dev/phase2/experiment.py run --receipt "$receipt" --nomad-addr "$nomad_addr" > "$workspace/recovery-worker.log" 2>&1 || status=1
    fi
  fi
  if [[ -f $workspace/phase2/service/receipt.json ]]; then
    .venv/bin/python dev/phase2/standing.py cleanup --receipt "$receipt" --nomad-addr "$nomad_addr" > "$workspace/recovery-service.log" 2>&1 || status=1
  fi
  echo "Slice 12 receipts and outputs saved under $workspace"
  exit "$status"
}
trap recover EXIT

.venv/bin/python dev/phase2/experiment.py seed --workspace "$workspace" --fixture dev/phase2/file-mode.json
.venv/bin/python dev/phase2/experiment.py render --receipt "$receipt" --image "$image" --mcp-url "${HARNESS_PHASE2_MCP_URL:-http://127.0.0.1:8001/mcp}"
echo 'Worker checkpoint, before submission'
cat "$workspace/phase2/prepared.json" "$workspace/phase2/job.json"
make nomad-up
.venv/bin/python dev/phase2/experiment.py run --receipt "$receipt" --nomad-addr "$nomad_addr"
.venv/bin/python dev/phase2/standing.py checkpoint --receipt "$receipt"
echo 'Service checkpoint, before explicit submission'
cat "$workspace/phase2/service/attempt.json" "$workspace/phase2/service/export.json" "$workspace/phase2/service/delivery/maintain-mode.sh" "$workspace/phase2/service/job.json"
.venv/bin/python dev/phase2/standing.py submit --receipt "$receipt" --nomad-addr "$nomad_addr"
.venv/bin/python dev/phase2/standing.py observe --receipt "$receipt" --nomad-addr "$nomad_addr"
.venv/bin/python dev/phase2/standing.py stop --receipt "$receipt" --nomad-addr "$nomad_addr"
