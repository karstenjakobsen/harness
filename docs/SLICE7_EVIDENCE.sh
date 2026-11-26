#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

exec uv run --locked --all-packages pytest -q -s -W error \
    packages/harness_operator/tests/test_goal_plan_live.py::test_advisory_chess_plan_reads_versioned_skills \
    packages/harness_mcp/tests/test_list_goals.py::test_catalog_import_and_historical_skill_reads
