#!/usr/bin/env bash
set -uo pipefail
cd -- "$(dirname -- "$0")/.."
output=docs/SLICE10_EVIDENCE.md
exec > >(tee "$output") 2>&1
echo '# Slice 10 verification'
echo
date -u '+Run at %Y-%m-%d %H:%M:%S UTC.'
echo
status=0
run_check() {
    local title=$1
    shift
    echo "## $title"
    echo
    echo '~~~text'
    "$@"
    local result=$?
    echo '~~~'
    echo
    echo "Exit code $result."
    echo
    if (( result != 0 )); then status=1; fi
}
run_check 'Worker image build' make worker-image
run_check 'Static checks' make check
run_check 'Offline tests' make test
run_check 'Real Nomad tests' make test-nomad
run_check 'Signed-in acceptance' env PYTEST_ADDOPTS=-s make test-live-extended
echo '## Interpretation'
echo
echo 'The Nomad transport fixture submits a controlled result through the real signed worker endpoint.'
echo 'The signed-in handoff test separately requires the operator and worker to produce and review their own result.'
echo 'A failed signed-in check leaves real handoff, fresh review and judgment acceptance pending.'
exit "$status"
