#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
mkdir -p .harness/phase2
workspace=$(mktemp -d "$PWD/.harness/phase2/slice13-XXXXXX")
receipt="$workspace/phase2/receipt.json"
nomad_addr=${HARNESS_NOMAD_ADDR:-http://127.0.0.1:14646}
image=$(docker image inspect --format '{{.Id}}' "${WORKER_IMAGE:-harness-worker:slice10}")
trap 'echo "Slice 13 workspace saved under $workspace"' EXIT

.venv/bin/python dev/phase2/experiment.py seed --workspace "$workspace"
.venv/bin/python dev/phase2/experiment.py render --receipt "$receipt" --image "$image" --mcp-url "${HARNESS_PHASE2_MCP_URL:-http://127.0.0.1:8001/mcp}"
echo 'Rendering checkpoint. The prepared attempt and exact job follow.'
cat "$workspace/phase2/prepared.json" "$workspace/phase2/job.json"
make nomad-up
attempt=$(.venv/bin/python -c 'import json,sys; print(json.load(open(sys.argv[1]))["attempt_id"])' "$receipt")
# The watcher reports the worker outcome; a failed worker still yields a capture.
.venv/bin/python dev/phase2/watch.py run --receipt "$receipt" --nomad-addr "$nomad_addr" || true
echo 'Replay after allocation cleanup'
.venv/bin/python dev/phase2/watch.py replay --workspace "$workspace" --attempt-id "$attempt"
