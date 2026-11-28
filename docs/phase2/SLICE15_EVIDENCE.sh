#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."

case ${1:-} in
    '') make check; make test; exit ;;
    --live) ;;
    *) echo 'Usage: SLICE15_EVIDENCE.sh [--live]' >&2; exit 2 ;;
esac

umask 077
make worker-image WORKER_IMAGE=harness-worker:codex-slice15
image=$(docker image inspect --format '{{.Id}}' harness-worker:codex-slice15)
mcp_url=http://127.0.0.1:8001/mcp
if [[ $(docker info --format '{{.OperatingSystem}}') == 'Docker Desktop' ]]; then
    mcp_url=http://host.docker.internal:8001/mcp
fi

mkdir -p dev/.harness/phase2
workspace=$(mktemp -d "$PWD/dev/.harness/phase2/slice15-XXXXXX")
trap 'echo "Slice 15 receipt and logs saved under $workspace"' EXIT
receipt="$workspace/phase2/receipt.json"
experiment=(.venv/bin/python dev/phase2/experiment.py)
"${experiment[@]}" seed --workspace "$workspace" >/dev/null
"${experiment[@]}" render --receipt "$receipt" --image "$image" \
    --worker codex --model gpt-5.6-luna --effort low --auth api-key \
    --nomad-variable --mcp-url "$mcp_url" >/dev/null
cat "$workspace/phase2/job.json"
env -u CODEX_API_KEY -u OPENAI_API_KEY "${experiment[@]}" run --receipt "$receipt"
