#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

exec uv run --locked --all-packages pytest -q -s -W error \
    packages/harness_operator/tests/test_goal_plan_live.py::test_delegated_operator_saves_subgoals \
    packages/harness_api/tests/test_delegated_definitions.py::test_subgoal_concurrent_retry_and_recovery_after_commit \
    packages/harness_api/tests/test_delegated_definitions.py::test_subgoal_audit_cannot_deny_an_applied_call \
    packages/harness_mcp/tests/test_list_goals.py::test_subgoal_tool_is_parent_scoped_and_audits_request_and_result \
    packages/harness_mcp/tests/test_list_goals.py::test_subgoal_discovery_tracks_withdrawal_and_regrant
