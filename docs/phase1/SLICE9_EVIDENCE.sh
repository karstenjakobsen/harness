#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
# This scenario verifies cold startup and owns the cluster it tears down.
dev/nomad/cluster.sh assert-down
trap 'make nomad-down' EXIT

echo 'Server-only startup and teardown without a systemd user session'
env -u XDG_RUNTIME_DIR make nomad-server
if output=$(env -u XDG_RUNTIME_DIR make nomad-down 2>&1); then
    echo 'Expected teardown to report unverified client cleanup.' >&2
    exit 1
fi
echo "$output"
dev/nomad/cluster.sh assert-down
[[ $output == *"client cleanup could not be verified"* ]]

echo 'Cold start and real workloads'
make test-nomad
first=$(dev/nomad/cluster.sh identity)
echo 'Repeat on the running cluster and test loss of the disposable client’s heartbeat'
key=$(sha256sum <<<"$(pwd -P)" | cut -c1-12)
HARNESS_NOMAD_TEST_CLIENT_UNIT="harness-nomad-client@$key.service" make test-nomad
[[ $(dev/nomad/cluster.sh identity) == "$first" ]]
echo "Reused $first"
echo 'Teardown and repeat teardown'
make nomad-down
make nomad-down
dev/nomad/cluster.sh assert-down
trap - EXIT
echo 'Verified the project server and host client are down.'
