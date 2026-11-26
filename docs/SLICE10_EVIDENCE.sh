#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

make check
make test
make test-live
make test-live-extended

docker image inspect \
  ghcr.io/icoretech/codex-docker:0.166.0@sha256:c0568397f66fb8cc22c541fbafe26948da5000d24770b0ac2e918517dfc02615 \
  --format 'Base image content ID: {{.Id}}; registry digests: {{json .RepoDigests}}'
docker image inspect "${WORKER_IMAGE:-harness-worker:slice10}" \
  --format 'Worker image content ID: {{.Id}}; default user: {{.Config.User}}'
git diff --check
