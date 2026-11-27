#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."

# The original worker acceptance requires the archived Slice 10 CLI.
if ! uv run --locked --package harness-operator operator work start --help >/dev/null 2>&1; then
  echo "Slice 10 worker dispatch is retired. Reproduce this historical recipe at the recorded Slice 10 baseline." >&2
  exit 1
fi

status=0
verify() {
  if "$@"; then
    printf '\nPASS: %s\n\n' "$*"
  else
    result=$?
    printf '\nFAIL (exit %s): %s\n\n' "$result" "$*"
    status=1
  fi
}

git log -1 --format='Source commit: %H %s'
verify make check
verify make test
verify make test-live
verify make test-live-extended

docker image inspect \
  ghcr.io/icoretech/codex-docker:0.166.0@sha256:c0568397f66fb8cc22c541fbafe26948da5000d24770b0ac2e918517dfc02615 \
  --format 'Base image content ID: {{.Id}}; registry digests: {{json .RepoDigests}}'
docker image inspect "${WORKER_IMAGE:-harness-worker:slice10}" \
  --format 'Worker image content ID: {{.Id}}; default user: {{.Config.User}}'
verify git diff --check
exit "$status"
