#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
# This scenario verifies cold startup and owns the cluster it tears down.
dev/nomad/cluster.sh assert-down
trap 'make nomad-down' EXIT

echo 'Cold start and three real workloads'
make test-nomad
first=$(dev/nomad/cluster.sh identity)
echo 'Repeat on the running cluster'
make test-nomad
[[ $(dev/nomad/cluster.sh identity) == "$first" ]]
echo "Reused $first"
echo 'Teardown and repeat teardown'
make nomad-down
make nomad-down
dev/nomad/cluster.sh assert-down
trap - EXIT
echo 'Verified the project server and host client are down.'
