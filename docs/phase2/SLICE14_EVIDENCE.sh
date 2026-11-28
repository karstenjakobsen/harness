#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."

case ${1:-} in
    '') make check; make test; exit ;;
    --probe|--live) ;;
    *) echo 'Usage: SLICE14_EVIDENCE.sh [--probe|--live]' >&2; exit 2 ;;
esac

codex_key_args=()
kiro_key_args=()
if [[ -n ${SLICE14_KIRO_KEY_FILE:-} ]]; then
    [[ -s $SLICE14_KIRO_KEY_FILE ]] || { echo 'Kiro key file is missing or empty.' >&2; exit 1; }
    kiro_key_args=(--api-key-file "$SLICE14_KIRO_KEY_FILE")
else
    : "${KIRO_API_KEY:?Set KIRO_API_KEY or SLICE14_KIRO_KEY_FILE for the Kiro probe and delivery.}"
fi
if [[ $1 == --live ]]; then
    if [[ -n ${SLICE14_CODEX_KEY_FILE:-} ]]; then
        [[ -s $SLICE14_CODEX_KEY_FILE ]] || { echo 'Codex key file is missing or empty.' >&2; exit 1; }
        codex_key_args=(--api-key-file "$SLICE14_CODEX_KEY_FILE")
    else
        : "${CODEX_API_KEY:?Set CODEX_API_KEY or SLICE14_CODEX_KEY_FILE for the Codex delivery.}"
    fi
fi

umask 077
mkdir -p dev/.harness/phase2
workspace=$(mktemp -d "$PWD/dev/.harness/phase2/slice14-XXXXXX")
probe="$workspace/phase2/receipt.json"
nomad_addr=${HARNESS_NOMAD_ADDR:-http://127.0.0.1:14646}
experiment=(.venv/bin/python dev/phase2/experiment.py)
trap 'echo "Slice 14 receipts and native event streams saved under $workspace"' EXIT

docker build --provenance=false --tag harness-worker:kiro-slice14 --file dev/worker/Dockerfile.Kiro .
kiro_image=$(docker image inspect --format '{{.Id}}' harness-worker:kiro-slice14)
kiro_model=${SLICE14_KIRO_MODEL:-claude-sonnet-4.6}
kiro_effort=${SLICE14_KIRO_EFFORT:-low}
codex_model=${SLICE14_CODEX_MODEL:-gpt-5.6-luna}
codex_effort=${SLICE14_CODEX_EFFORT:-low}

render_and_run() {
    local receipt=$1 engine=$2 image=$3 model=$4 effort=$5
    shift 5
    local render_args=()
    local result=0
    if [[ ${1:-} == --brief-only ]]; then
        render_args=(--brief-only)
        shift
    fi
    "${experiment[@]}" render --receipt "$receipt" --image "$image" \
        --worker "$engine" --model "$model" --effort "$effort" --auth api-key \
        --mcp-url "${HARNESS_PHASE2_MCP_URL:-http://127.0.0.1:8001/mcp}" "${render_args[@]}" >/dev/null
    cat -- "$(dirname -- "$receipt")/job.json"
    "${experiment[@]}" run --receipt "$receipt" --nomad-addr "$nomad_addr" "$@" >/dev/null || result=$?
    .venv/bin/python - "$receipt" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
receipt = json.loads(path.read_text())
execution = receipt.get("execution") or {}
audit = path.parent / "evidence/harness-after.json"
summary = {
    key: receipt[key]
    for key in ("attempt_id", "work_item_id", "goal_revision", "job_id", "image", "launch")
}
summary["execution"] = {
    key: execution.get(key)
    for key in (
        "allocation_id", "exit_code", "verified", "brief_read", "cli_version",
        "worker_sessions", "ai_operator_sessions", "activity_capture",
        "artifact_id", "file_sha256", "grant_id",
    )
}
if audit.is_file():
    summary["calls"] = [
        {key: call[key] for key in ("tool", "outcome", "attempt_id", "grant_id", "artifact_id")}
        for call in json.loads(audit.read_text())["calls"]
    ]
print(json.dumps(summary, ensure_ascii=False, indent=2))
PY
    return "$result"
}

"${experiment[@]}" seed --workspace "$workspace" >/dev/null
render_and_run "$probe" kiro "$kiro_image" "$kiro_model" "$kiro_effort" --brief-only "${kiro_key_args[@]}"
if [[ $1 == --probe ]]; then
    exit
fi

make worker-image WORKER_IMAGE=harness-worker:codex-slice14
codex_image=$(docker image inspect --format '{{.Id}}' harness-worker:codex-slice14)
"${experiment[@]}" prepare --receipt "$probe" --attempt-id slice14-codex >/dev/null
render_and_run "$workspace/phase2/attempts/slice14-codex/receipt.json" codex "$codex_image" "$codex_model" "$codex_effort" "${codex_key_args[@]}"

"${experiment[@]}" prepare --receipt "$probe" --attempt-id slice14-kiro >/dev/null
render_and_run "$workspace/phase2/attempts/slice14-kiro/receipt.json" kiro "$kiro_image" "$kiro_model" "$kiro_effort" "${kiro_key_args[@]}"
