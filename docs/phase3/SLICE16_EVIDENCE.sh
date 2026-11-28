#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."

uv run --locked --all-packages pytest -q packages/harness_api/tests/test_work_delegation.py
uv run --locked --package harness-api python - <<'PY'
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from harness_api import GoalAPI, OperatorAPI, WorkAPI, WorkspaceInput

with TemporaryDirectory(prefix="harness-slice16-") as directory:
    path = Path(directory) / "workspace.sqlite3"
    goals, work = GoalAPI(path), WorkAPI(path)
    goal = goals.create_goal("Prepare a library report", status="active")
    operator = OperatorAPI(path).register_operator("Builder")
    grant = work.grant_delegation(goal["id"], operator["id"])
    run = goals.start_run(delegation_grant_id=grant["id"])
    call = goals.start_tool_call(
        run["id"], "delegate_work", target_goal_id=goal["id"], target_revision=1
    )
    item = work.delegate_work(
        goal["id"], 1, "Write a report; leave the goal open.",
        WorkspaceInput(source_path=None, base_sha=None), "library-report", call=call,
    )
    # Leave reply delivery unfinished; all committed facts must survive reopening.
    reopened = WorkAPI(path)
    saved = reopened.get_work_item(item["id"])
    history = GoalAPI(path).get_run(run["id"])
    assert saved == item and saved["committing_call"] == call
    assert history["calls"][0]["committed_work_item_id"] == saved["id"]
    assert history["calls"][0]["outcome"] == "unfinished"
    attempts = reopened.list_attempts(saved["id"])
    assert attempts == []
    assert goals.get_goal(goal["id"])["status"] == "active"
    assert goals.get_goal(goal["id"])["revision"] == 1
    print(json.dumps({
        "work_item_id": saved["id"], "goal_id": saved["goal_id"],
        "goal_revision": saved["goal_revision"], "operator_id": saved["operator_id"],
        "delegation_grant_id": saved["delegation_grant_id"],
        "committing_call": saved["committing_call"],
        "call_outcome": history["calls"][0]["outcome"],
        "reopened": True, "attempt_count": len(attempts), "goal_status": "active",
    }, indent=2))
print("Live checks: not required; Slice 16 adds Python model operations only.")
PY
