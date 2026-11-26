#!/usr/bin/env bash
set -uo pipefail
cd -- "$(dirname -- "$0")/.."
exec > >(tee docs/SLICE10A_EVIDENCE.md) 2>&1
echo '# Slice 10a verification'
echo
date -u '+Run at %Y-%m-%d %H:%M:%S UTC.'
status=0
run_check() {
    local title=$1 start=$SECONDS rc=0
    shift
    echo
    echo "## $title"
    echo
    echo '~~~text'
    "$@" || rc=$?
    echo '~~~'
    echo
    echo "Exit code $rc. Elapsed $((SECONDS-start)) s."
    if (( rc != 0 )); then status=1; fi
}
selection() (
    set -eu
    temporary=$(mktemp -d)
    trap 'rm -rf -- "$temporary"' EXIT
    for target in test-live test-live-extended; do
        PYTEST_ADDOPTS='--collect-only -q' make "$target" > "$temporary/$target.log"
        awk '/^packages\/.*::/ {print}' "$temporary/$target.log" | sort > "$temporary/$target"
        echo "$target"
        cat "$temporary/$target"
    done
    test "$(wc -l < "$temporary/test-live")" = 1
    grep -q '::test_danish_city_file_handoff$' "$temporary/test-live"
    test -s "$temporary/test-live-extended"
    test -z "$(comm -12 "$temporary/test-live" "$temporary/test-live-extended")"
    echo 'The two selections have disjoint test IDs.'
)
run_check 'Pytest collection' selection
run_check 'Static checks' make check
run_check 'Offline tests' env PYTHONWARNINGS=error make test
run_check 'Cluster startup or reuse' make nomad-up
run_check 'Worker image build or reuse' make .harness/nomad/worker-image
run_check 'Real Nomad isolation and execution' make test-nomad
run_check 'Warm Danish-city file handoff' env PYTEST_ADDOPTS=-s make test-live
run_check 'Extended signed-in scenarios' env PYTEST_ADDOPTS=-s make test-live-extended
exit "$status"
