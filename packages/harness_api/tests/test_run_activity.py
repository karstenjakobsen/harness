import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from harness_api import (
    GoalAPI,
    GoalNotFoundError,
    GoalStorageError,
    GoalValidationError,
    OperatorAPI,
    RunNotFoundError,
)
from harness_api.app import create_app


def test_denied_read_does_not_attach_to_goal_created_later(tmp_path):
    path = tmp_path / "goals.db"
    api = GoalAPI(path)
    run_id = api.start_run()["id"]
    attempt = api.start_tool_call(run_id, "get_goal_progress", target_goal_id=1)
    with pytest.raises(GoalNotFoundError):
        api.get_goal_progress(1)
    api.finish_tool_call(attempt, "denied")
    api.finish_run(run_id, "succeeded")

    goal_id = api.create_goal("First goal")["id"]
    assert goal_id == 1
    reopened = GoalAPI(path)
    (call,) = reopened.get_run(run_id)["calls"]
    assert call["target_goal_id"] == goal_id and call["outcome"] == "denied"
    (revision,) = reopened.get_goal_activity(goal_id)["timeline"]
    assert revision["kind"] == "revision"


def test_history_reads_can_exclude_only_the_matching_unfinished_call(tmp_path):
    api = GoalAPI(tmp_path / "goals.db")
    goal_id = api.create_goal("Library")["id"]
    other_goal = api.create_goal("Other")["id"]
    run_id = api.start_run()["id"]
    other_run = api.start_run()["id"]
    goal_call = api.start_tool_call(run_id, "get_goal_activity", target_goal_id=goal_id)
    run_call = api.start_tool_call(run_id, "get_run", target_run_id=run_id)

    with pytest.raises(GoalValidationError):
        api.get_goal_activity(goal_id, call=run_call)
    with pytest.raises(GoalValidationError):
        api.get_goal_activity(other_goal, call=goal_call)
    with pytest.raises(GoalValidationError):
        api.get_run(other_run, call=run_call)

    snapshot = api.get_run(run_id, call=run_call)
    assert [item["sequence"] for item in snapshot["calls"]] == [goal_call["sequence"]]
    api.finish_tool_call(run_call, "returned", history_result=snapshot)
    with pytest.raises(GoalValidationError):
        api.get_run(run_id, call=run_call)


def test_finished_history_read_cannot_record_its_own_call_as_returned(tmp_path):
    api = GoalAPI(tmp_path / "goals.db")
    goal_id = api.create_goal("Library")["id"]
    run_id = api.start_run()["id"]
    goal_call = api.start_tool_call(run_id, "get_goal_activity", target_goal_id=goal_id)
    run_call = api.start_tool_call(run_id, "get_run", target_run_id=run_id)

    for call, history in (
        (goal_call, api.get_goal_activity(goal_id)),
        (run_call, api.get_run(run_id)),
    ):
        with pytest.raises(GoalValidationError):
            api.finish_tool_call(call, "returned", history_result=history)

    assert [call["outcome"] for call in api.get_run(run_id)["calls"]] == [
        "unfinished",
        "unfinished",
    ]


def test_completion_attempt_commit_and_delivery_are_independent(tmp_path):
    path = tmp_path / "goals.db"
    api = GoalAPI(path)
    parent = api.create_goal("Parent", status="active")["id"]
    child = api.create_goal("Child", parent_goal_id=parent, status="active")["id"]
    operator = OperatorAPI(path).register_operator("Reviewer")["id"]
    grant = api.grant_completion(child, operator)["id"]
    report = api.record_observation(child, confirmation="Verified", retry_key="report")
    run_id = api.start_run(grant)["id"]

    def complete(call, grant_id=grant):
        return GoalAPI(path).complete_goal(
            child,
            1,
            call=call,
            completion_grant_id=grant_id,
            evidence_ids=[report["evidence_id"]],
            rationale="Verified",
        )

    def attempt():
        return api.start_tool_call(
            run_id, "complete_goal", target_goal_id=child, target_revision=1
        )

    interrupted = attempt()
    (first,) = GoalAPI(path).get_run(run_id)["calls"]
    assert first["sequence"] == interrupted["sequence"]
    assert first["outcome"] == "unfinished" and first["committed_event_id"] is None
    assert first["finished_at"] is None and first["returned_goals"] is None
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.executescript("""
            CREATE TRIGGER fail_commit_link BEFORE UPDATE OF committed_event_id ON run_calls
            BEGIN SELECT RAISE(ABORT, 'forced link failure'); END;
        """)
        rolled_back = attempt()
        with pytest.raises(GoalStorageError):
            complete(rolled_back)
        reopened = GoalAPI(path)
        assert reopened.get_goal(child)["status"] == "active"
        assert not reopened.get_goal_history(child)[0]["completion"]
        _, second = reopened.get_run(run_id)["calls"]
        assert (
            second["outcome"] == "unfinished" and second["committed_event_id"] is None
        )
        db.execute("DROP TRIGGER fail_commit_link")

    # A run ID and matching target cannot lend completion authority to an advisory attempt.
    advisory = api.start_run()["id"]
    unbound = api.start_tool_call(
        advisory, "complete_goal", target_goal_id=child, target_revision=1
    )
    with pytest.raises(GoalValidationError, match="does not match"):
        complete(unbound)

    committing = attempt()
    decision = complete(committing)
    reopened = GoalAPI(path)
    saved_run = reopened.get_run(run_id)
    committed = saved_run["calls"][-1]
    assert saved_run["outcome"] == "unfinished"
    assert committed["committed_event_id"] == decision["event_id"]
    assert committed["outcome"] == "unfinished" and committed["returned_goals"] is None
    assert reopened.get_goal(child)["status"] == "completed"
    assert reopened.get_goal(parent)["status"] == "active"
    (entry,) = [
        entry
        for entry in reopened.get_goal_activity(child)["timeline"]
        if entry["kind"] == "decision"
    ]
    assert entry["decision"] == decision and entry["committing_call"] == committing

    with pytest.raises(GoalValidationError, match="saved decision"):
        api.finish_tool_call(
            unbound,
            "returned",
            returned_goals=[
                {
                    "goal_id": child,
                    "revision": 1,
                    "status": None,
                    "observation_ids": [],
                    "decision": {
                        "event_id": decision["event_id"],
                        "evidence_ids": decision["evidence_ids"],
                        "statement_evidence_id": None,
                    },
                }
            ],
        )
    assert api.get_run(advisory)["calls"][0]["outcome"] == "unfinished"

    retry = attempt()
    assert complete(retry) == decision
    retrieved = reopened.get_run(run_id)["calls"][-1]
    assert retrieved["retrieved_event_id"] == decision["event_id"]
    assert retrieved["committed_event_id"] is None

    api.withdraw_completion(grant)
    replacement = api.grant_completion(child, operator)["id"]
    denied = attempt()
    with pytest.raises(GoalValidationError, match="inactive"):
        complete(denied)
    with pytest.raises(GoalValidationError, match="does not match"):
        complete(denied, replacement)
    api.finish_tool_call(denied, "denied")
    api.finish_run(run_id, "failed")
    saved_run = api.get_run(run_id)
    assert (
        saved_run["outcome"] == "failed"
        and saved_run["calls"][0]["outcome"] == "unfinished"
    )
    last = saved_run["calls"][-1]
    assert (
        last["outcome"] == "denied"
        and last["target_goal_id"] == child
        and last["target_revision"] == 1
    )
    assert last["committed_event_id"] is None and last["retrieved_event_id"] is None
    assert api.get_goal_history(child)[0]["completion"] == decision
    assert any(
        item["kind"] == "call"
        and item["run_id"] == run_id
        and item["sequence"] == denied["sequence"]
        and item["relationship"] == "completion_target"
        and item["outcome"] == "denied"
        for item in api.get_goal_activity(child)["timeline"]
    )


def test_owner_scope_order_and_http_contract(tmp_path):
    path = tmp_path / "goals.db"
    api = GoalAPI(path)
    goal_id = api.create_goal("Review")["id"]
    report = api.record_observation(
        goal_id, confirmation="Verified", retry_key="report"
    )
    run_id = api.start_run()["id"]
    first = api.start_tool_call(run_id, "get_goal_progress", target_goal_id=goal_id)
    api.finish_tool_call(
        first,
        "returned",
        returned_goals=[
            {
                "goal_id": goal_id,
                "revision": 1,
                "status": "draft",
                "decision": None,
                "observation_ids": [report["evidence_id"]],
            }
        ],
    )
    second = api.start_tool_call(run_id, "get_goal_tree", target_goal_id=goal_id)
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.executescript("""
            UPDATE goal_revisions SET created_at = '2025-01-01 10:00:00';
            UPDATE goal_events SET recorded_at = '2025-01-01 10:00:00';
            UPDATE run_calls SET started_at = '2025-01-01 10:00:00';
            INSERT INTO users (id, username, display_name) VALUES (2, 'other', 'Other');
            INSERT INTO goals (id, owner_user_id) VALUES (2, 2);
            INSERT INTO operator_runs (id, owner_user_id, started_at) VALUES (2, 2, '2025-01-01 10:00:00');
            INSERT INTO run_calls (run_id, sequence, tool, target_goal_id, resolved_goal_id, started_at)
            VALUES (2, 1, 'get_goal_progress', 1, 1, '2025-01-01 10:00:00');
        """)
    with pytest.raises(GoalValidationError, match="workspace owner"):
        api.finish_tool_call(
            second,
            "returned",
            returned_goals=[
                {
                    "goal_id": 2,
                    "revision": None,
                    "status": "draft",
                    "observation_ids": [],
                    "decision": None,
                }
            ],
        )
    activity = api.get_goal_activity(goal_id)
    assert [item["kind"] for item in activity["timeline"]] == [
        "revision",
        "observation",
        "call",
        "call",
    ]
    assert [
        (item["run_id"], item["sequence"])
        for item in activity["timeline"]
        if item["kind"] == "call"
    ] == [(run_id, first["sequence"]), (run_id, second["sequence"])]
    assert [call["sequence"] for call in api.get_run(run_id)["calls"]] == [
        first["sequence"],
        second["sequence"],
    ]
    with pytest.raises(GoalNotFoundError):
        api.get_goal_activity(2)
    with pytest.raises(RunNotFoundError):
        api.get_run(2)
    with TestClient(create_app(path)) as client:
        assert client.get(f"/goals/{goal_id}/history?view=activity").json() == activity
        assert client.get(f"/goals/{goal_id}/history").json() == api.get_goal_history(
            goal_id
        )
        assert client.get(f"/runs/{run_id}").json() == api.get_run(run_id)
        assert client.get("/goals/2/history?view=activity").status_code == 404
        assert client.get("/runs/2").status_code == 404
