import sqlite3
from contextlib import closing
from pathlib import Path

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


def test_upgrade_v8_keeps_delegated_decision_and_citation_without_run_attribution(
    tmp_path,
):
    path = tmp_path / "goals.db"
    snapshot = Path(__file__).with_name("fixtures") / "schema_v8.sql"
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.executescript(snapshot.read_text(encoding="utf-8"))
        db.executescript("""
            INSERT INTO operators (id, owner_user_id, name) VALUES (21, 1, 'Reviewer');
            INSERT INTO goals (id, owner_user_id, status, parent_goal_id)
            VALUES (22, 1, 'active', NULL), (23, 1, 'completed', 22);
            INSERT INTO goal_revisions (goal_id, revision, title)
            VALUES (22, 1, 'Parent'), (23, 1, 'Original'), (23, 2, 'Updated');
            INSERT INTO goal_assignments (id, goal_id, operator_id, completion_granted_at)
            VALUES (24, 23, 21, '2025-01-01 10:00:00');
            INSERT INTO goal_events (id, goal_id, revision, kind, actor_user_id, payload, retry_key)
            VALUES (25, 23, 1, 'observation', 1, '{"evidence_kind":"owner_confirmation","evidence":"Confirmed"}', 'report');
            INSERT INTO goal_events (id, goal_id, revision, kind, completion_grant_id, payload)
            VALUES (26, 23, 2, 'completion', 24, '{"rationale":"Confirmed by owner"}');
            INSERT INTO completion_citations VALUES (23, 26, 25);
        """)
    GoalAPI(path)
    reopened = GoalAPI(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (12,)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert reopened.get_goal(23)["parent_goal_id"] == 22
    assert reopened.get_completion_grant(24) == {
        "id": 24,
        "goal_id": 23,
        "operator_id": 21,
    }
    previous, current = reopened.get_goal_history(23)
    assert (previous["revision"], previous["title"]) == (1, "Original")
    assert (
        previous["evidence"][0]["evidence_id"] == 25
        and previous["evidence"][0]["submitted_by"] == 1
    )
    decision = current["completion"]
    assert decision is not None
    assert (
        decision["event_id"] == 26
        and decision["revision"] == 2
        and decision["evidence_ids"] == [25]
    )
    assert (
        decision.get("recorded_by_operator_id") == 21
        and decision.get("completion_grant_id") == 24
    )
    timeline = reopened.get_goal_activity(23)["timeline"]
    assert all(item["kind"] != "call" for item in timeline)
    last = timeline[-1]
    assert last["kind"] == "decision"
    assert last["decision"] == decision and last["committing_call"] is None


@pytest.mark.parametrize("version", [9, 10, 11])
def test_upgrade_keeps_confirmed_goal_relationships(tmp_path, version):
    path = tmp_path / "goals.db"
    snapshot = Path(__file__).with_name("fixtures") / f"schema_v{version}.sql"
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.executescript(snapshot.read_text(encoding="utf-8"))
        db.executescript("""
            INSERT INTO operators (id, owner_user_id, name) VALUES (1, 1, 'Reviewer');
            INSERT INTO goals (id, owner_user_id, status, parent_goal_id, created_at)
            VALUES (1, 1, 'active', NULL, '2025-01-01 10:00:02'),
                   (2, 1, 'completed', 1, '2025-01-01 10:00:02');
            INSERT INTO goal_revisions (goal_id, revision, title, created_at)
            VALUES (1, 1, 'Parent', '2025-01-01 10:00:02'),
                   (2, 1, 'Child', '2025-01-01 10:00:02');
            INSERT INTO goal_assignments (id, goal_id, operator_id, completion_granted_at, released_at)
            VALUES (1, 2, 1, '2025-01-01 10:00:03', '2025-01-01 10:00:06');
            INSERT INTO goal_events (id, goal_id, revision, kind, actor_user_id, payload, recorded_at)
            VALUES (1, 2, 1, 'observation', 1, '{"evidence_kind":"owner_confirmation","evidence":"Verified"}',
                    '2025-01-01 10:00:03');
            INSERT INTO goal_events (id, goal_id, revision, kind, completion_grant_id, payload, recorded_at)
            VALUES (2, 2, 1, 'completion', 1, '{"rationale":"Verified"}', '2025-01-01 10:00:05');
            INSERT INTO completion_citations VALUES (2, 2, 1);

            INSERT INTO operator_runs (id, owner_user_id, completion_grant_id, started_at, finished_at, outcome)
            VALUES (1, 1, NULL, '2025-01-01 10:00:00', '2025-01-01 10:00:01', 'succeeded'),
                   (2, 1, NULL, '2025-01-01 10:00:03', '2025-01-01 10:00:04', 'succeeded'),
                   (3, 1, 1, '2025-01-01 10:00:04', NULL, 'unfinished');
            INSERT INTO run_calls (
                run_id, sequence, tool, target_goal_id, target_revision,
                started_at, finished_at, outcome, committed_event_id
            ) VALUES
                (1, 1, 'get_goal_progress', 2, NULL, '2025-01-01 10:00:00', '2025-01-01 10:00:01', 'denied', NULL),
                (2, 1, 'get_goal_progress', 2, NULL, '2025-01-01 10:00:03', '2025-01-01 10:00:04', 'returned', NULL),
                (3, 1, 'complete_goal', 2, 1, '2025-01-01 10:00:05', NULL, 'unfinished', 2),
                (3, 2, 'complete_goal', 2, 1, '2025-01-01 10:00:07', '2025-01-01 10:00:08', 'denied', NULL);
            INSERT INTO run_call_goals (run_id, sequence, position, goal_id, revision, status, observation_ids)
            VALUES (2, 1, 0, 2, 1, 'active', '[1]');
        """)
        if version >= 10:
            db.execute(
                "UPDATE run_calls SET resolved_goal_id = 2 WHERE run_id IN (2, 3)"
            )
        if version == 11:
            db.executescript("""
                INSERT INTO goal_revisions (goal_id, revision, title, created_at)
                VALUES (1, 2, 'Revised parent', '2025-01-01 10:00:10');
                INSERT INTO goal_definition_grants (id, operator_id, goal_id, action, granted_at)
                VALUES (1, 1, 1, 'revise_goal', '2025-01-01 10:00:09');
                INSERT INTO operator_runs (id, owner_user_id, definition_grant_id, started_at)
                VALUES (4, 1, 1, '2025-01-01 10:00:10');
                INSERT INTO run_calls (run_id, sequence, tool, target_goal_id, target_revision,
                                       started_at, resolved_goal_id)
                VALUES (4, 1, 'revise_goal', 1, 1, '2025-01-01 10:00:10', 1);
                INSERT INTO run_call_revisions (run_id, sequence, goal_id, revision, kind)
                VALUES (4, 1, 1, 2, 'committed');
            """)

    GoalAPI(path)
    reopened = GoalAPI(path)
    (missing,) = reopened.get_run(1)["calls"]
    assert (missing["target_goal_id"], missing["outcome"]) == (2, "denied")
    assert (
        missing["committed_revision"] is None and missing["retrieved_revision"] is None
    )
    (read,) = reopened.get_run(2)["calls"]
    assert read["returned_goals"][0]["observation_ids"] == [1]
    assert reopened.get_run(3)["definition_grant"] is None
    assert reopened.get_run(3)["completion_grant_id"] == 1
    assert reopened.get_goal(2)["parent_goal_id"] == 1
    timeline = reopened.get_goal_activity(2)["timeline"]
    assert [
        (entry["run_id"], entry["sequence"], entry["relationship"], entry["outcome"])
        for entry in timeline
        if entry["kind"] == "call"
    ] == [
        (2, 1, "requested", "returned"),
        (3, 1, "completion_target", "unfinished"),
        (3, 2, "completion_target", "denied"),
    ]
    (decision,) = [entry for entry in timeline if entry["kind"] == "decision"]
    (revision,) = [entry for entry in timeline if entry["kind"] == "revision"]
    assert revision["committing_call"] is None
    assert decision["decision"]["evidence_ids"] == [1]
    assert decision["committing_call"] == {"run_id": 3, "sequence": 1}
    if version == 11:
        run = reopened.get_run(4)
        assert run["definition_grant"] == {
            "id": 1,
            "operator_id": 1,
            "action": "revise_goal",
            "goal_id": 1,
        }
        (call,) = run["calls"]
        assert call["committed_revision"] == {"goal_id": 1, "revision": 2}
        assert call["returned_history"] is None and call["target_run_id"] is None
        revisions = [
            entry
            for entry in reopened.get_goal_activity(1)["timeline"]
            if entry["kind"] == "revision"
        ]
        assert revisions[1]["committing_call"] == {"run_id": 4, "sequence": 1}
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (12,)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
