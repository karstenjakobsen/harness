#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."

exec uv run --locked --all-packages pytest -q -s -W error \
    packages/harness_operator/tests/test_goal_plan_live.py::test_operator_reconstructs_another_operators_revision \
    packages/harness_mcp/tests/test_list_goals.py::test_history_reads_keep_the_state_seen_by_another_operator
