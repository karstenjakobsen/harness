import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from harness_api import (
    GoalAPI,
    GoalStorageError,
    GoalValidationError,
    OperatorAPI,
    UserAPI,
)


@pytest.fixture
def workspace(tmp_path):
    path = tmp_path / "goals.db"
    api = GoalAPI(path)
    operators = OperatorAPI(path)
    parent = api.create_goal("Parent", status="active")["id"]
    child = api.create_goal("Child", parent_goal_id=parent, status="active")["id"]
    operator_id = operators.register_operator("Reviewer")["id"]
    report = api.record_observation(child, confirmation="Verified", retry_key="report")
    return path, api, operators, parent, child, operator_id, report


@pytest.fixture
def v7_workspace(tmp_path):
    path = tmp_path / "goals.db"
    snapshot = Path(__file__).with_name("fixtures") / "schema_v7.sql"
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.executescript(snapshot.read_text(encoding="utf-8"))
        db.executescript("""
            INSERT INTO operators (name, owner_user_id) VALUES ('Reviewer', 1);
            INSERT INTO goals (owner_user_id, status) VALUES (1, 'active');
            INSERT INTO goals (owner_user_id, status, parent_goal_id)
                VALUES (1, 'active', 1), (1, 'completed', 1);
            INSERT INTO goal_revisions (goal_id, revision, title)
                VALUES (1, 1, 'Parent'), (2, 1, 'Child'), (3, 1, 'Previous');
            INSERT INTO goal_assignments (goal_id, operator_id, claimed_at)
                VALUES (2, 1, '2025-01-01 10:00:00');
            INSERT INTO goal_events (goal_id, revision, kind, actor_user_id, payload) VALUES
                (2, 1, 'observation', 1, '{"evidence_kind":"owner_confirmation","evidence":"Verified"}'),
                (3, 1, 'observation', 1, '{"evidence_kind":"owner_confirmation","evidence":"Prior report"}'),
                (3, 1, 'observation', 1, '{"evidence_kind":"owner_confirmation","evidence":"Prior statement"}');
            INSERT INTO goal_events (goal_id, revision, kind, actor_user_id, payload, statement_evidence_id)
                VALUES (3, 1, 'completion', 1, '{}', 3);
            INSERT INTO completion_citations VALUES (3, 4, 2);
            UPDATE sqlite_sequence SET seq = 20 WHERE name = 'goal_events';
        """)
    return path


def test_upgrade_keeps_responsibility_and_owner_completion_without_grant(v7_workspace):
    path = v7_workspace
    UserAPI(path)
    api = GoalAPI(path)
    history = api.get_goal_history(2)
    assert api.get_goal(2)["operator"] == "Reviewer"
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (13,)
        assert db.execute("""
            SELECT id, goal_id, operator_id, claimed_at, released_at, completion_granted_at
            FROM goal_assignments
        """).fetchall() == [(1, 2, 1, "2025-01-01 10:00:00", None, None)]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        db.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            db.execute("""
                INSERT INTO goal_events (goal_id, revision, kind, payload, completion_grant_id)
                VALUES (2, 1, 'completion', '{"rationale":"Verified"}', 1)
            """)
    assert api.get_goal(3)["completion"] == api.complete_goal(
        3, 1, confirmation="Prior statement", evidence_ids=[2]
    )

    def complete(grant_id):
        return api.complete_goal(
            2,
            1,
            completion_grant_id=grant_id,
            rationale="Verified by the owner",
            evidence_ids=[1],
        )

    with pytest.raises(GoalValidationError, match="grant"):
        api.get_completion_grant(1)
    with pytest.raises(GoalValidationError, match="grant"):
        complete(1)
    with pytest.raises(GoalValidationError, match="Definition grant"):
        api.start_run(definition_grant_id=1)
    advisory = api.start_run()["id"]
    with pytest.raises(GoalValidationError, match="does not match"):
        api.create_delegated_goal(
            "Another",
            retry_key="other",
            call=api.start_tool_call(advisory, "create_goal"),
        )
    with pytest.raises(GoalValidationError, match="does not match"):
        api.revise_delegated_goal(
            2,
            1,
            title="Revised",
            call=api.start_tool_call(
                advisory,
                "revise_goal",
                target_goal_id=2,
                target_revision=1,
            ),
        )
    assert api.get_goal(2)["status"] == "active"
    assert api.get_goal_history(2) == history

    grant = api.grant_completion(2, 1)
    assert grant["id"] > 1
    decision = complete(grant["id"])
    assert decision["event_id"] == 21
    assert decision["recorded_by_operator_id"] == 1
    assert api.get_goal_history(2)[0]["evidence"] == history[0]["evidence"]


def test_failed_v7_upgrade_leaves_assignments_and_completion_history_intact(
    v7_workspace,
):
    with closing(sqlite3.connect(v7_workspace, autocommit=True)) as db:
        # Simulate a broken reference written outside Harness.
        db.execute("""
            INSERT INTO completion_citations (goal_id, decision_id, evidence_id)
            VALUES (3, 4, 99)
        """)
        with pytest.raises(GoalStorageError):
            GoalAPI(v7_workspace)
        assert db.execute("PRAGMA user_version").fetchone() == (7,)
        assert db.execute("SELECT * FROM goal_assignments").fetchall() == [
            (1, 2, 1, "2025-01-01 10:00:00", None)
        ]
        assert db.execute(
            "SELECT decision_id, evidence_id FROM completion_citations ORDER BY evidence_id"
        ).fetchall() == [(4, 2), (4, 99)]
        db.execute("DELETE FROM completion_citations WHERE evidence_id = 99")
    assert GoalAPI(v7_workspace).get_goal(3)["completion"]["evidence_ids"] == [2]


@pytest.mark.parametrize("withdraw_before_regrant", [True, False])
def test_regrant_always_invalidates_the_previous_grant(
    workspace, withdraw_before_regrant
):
    _, api, _, _, child, operator_id, report = workspace
    first = api.grant_completion(child, operator_id)
    request = {"rationale": "Verified", "evidence_ids": [report["evidence_id"]]}
    if withdraw_before_regrant:
        api.withdraw_completion(first["id"])
        with pytest.raises(GoalValidationError, match="grant"):
            api.complete_goal(child, 1, completion_grant_id=first["id"], **request)
    second = api.grant_completion(child, operator_id)
    assert second["id"] > first["id"]
    with pytest.raises(GoalValidationError, match="grant"):
        api.complete_goal(child, 1, completion_grant_id=first["id"], **request)
    assert api.get_goal(child)["status"] == "active"
    assert api.get_goal_history(child)[0]["completion"] is None
    assert api.complete_goal(child, 1, completion_grant_id=second["id"], **request)


def test_delegated_completion_cites_earlier_revision_with_its_original_attribution(
    workspace,
):
    path, api, _, parent, child, operator_id, report = workspace
    api.update_goal(child, success_criteria="Reviewed by owner")
    another = api.record_observation(child, reference="app:ref", retry_key="reference")
    grant = api.grant_completion(child, operator_id)
    ids = [report["evidence_id"], another["evidence_id"]]
    decision = api.complete_goal(
        child,
        2,
        completion_grant_id=grant["id"],
        rationale="Reviewed",
        evidence_ids=ids,
    )
    assert decision["revision"] == 2
    assert decision["recorded_by_operator_id"] == operator_id
    assert decision["completion_grant_id"] == grant["id"]
    assert decision["rationale"] == "Reviewed"
    assert decision["evidence_ids"] == ids
    assert (
        api.complete_goal(
            child,
            2,
            completion_grant_id=grant["id"],
            rationale=" Reviewed ",
            evidence_ids=[ids[1], ids[0], ids[0]],
        )
        == decision
    )
    with pytest.raises(GoalValidationError, match="different completion"):
        api.complete_goal(
            child,
            2,
            completion_grant_id=grant["id"],
            rationale="Other",
            evidence_ids=ids,
        )
    api.withdraw_completion(grant["id"])
    with pytest.raises(GoalValidationError, match="grant"):
        api.complete_goal(
            child,
            2,
            completion_grant_id=grant["id"],
            rationale="Reviewed",
            evidence_ids=ids,
        )
    reopened = GoalAPI(path)
    prior, current = reopened.get_goal_history(child)
    assert prior["evidence"] == [report] and current["evidence"] == [another]
    assert current["completion"] == decision
    assert reopened.get_goal(child)["status"] == "completed"
    assert reopened.get_goal(parent)["status"] == "active"


def test_delegation_validates_owner_target_revision_and_evidence(workspace):
    path, api, operators, parent, child, operator_id, report = workspace
    user = UserAPI(path).create_user("Other owner")
    other_operator = operators.register_operator("Other reviewer", user["id"])
    with pytest.raises(GoalValidationError, match="operator"):
        api.grant_completion(child, other_operator["id"])
    with pytest.raises(GoalValidationError, match="subgoal"):
        api.grant_completion(parent, operator_id)
    with pytest.raises(GoalValidationError, match="owner"):
        GoalAPI(path, local_owner=False).grant_completion(child, operator_id)
    grant = api.grant_completion(child, operator_id)
    sibling = api.create_goal("Sibling", parent_goal_id=parent)["id"]
    other_report = api.record_observation(
        sibling, confirmation="Elsewhere", retry_key="other"
    )
    request = {
        "completion_grant_id": grant["id"],
        "rationale": "Verified",
        "evidence_ids": [report["evidence_id"]],
    }
    for goal_id in (parent, sibling):
        with pytest.raises(GoalValidationError, match="grant"):
            api.complete_goal(goal_id, 1, **request)
    with pytest.raises(GoalValidationError, match="Stale revision"):
        api.complete_goal(child, 2, **request)
    for changes in (
        {"evidence_ids": []},
        {"evidence_ids": [other_report["evidence_id"]]},
        {"evidence_ids": [999]},
        {"rationale": "  "},
        {"confirmation": "Forged"},
    ):
        with pytest.raises(GoalValidationError):
            api.complete_goal(child, 1, **(request | changes))
    operators.unregister_operator(operator_id)
    with pytest.raises(GoalValidationError, match="grant"):
        api.complete_goal(child, 1, **request)
    assert api.get_goal(child)["status"] == "active"
    history = api.get_goal_history(child)[0]
    assert history["completion"] is None and history["evidence"] == [report]


def test_failed_delegated_transition_rolls_back_decision_and_citations(workspace):
    path, api, _, _, child, operator_id, report = workspace
    grant = api.grant_completion(child, operator_id)
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.executescript("""
            CREATE TRIGGER fail_completion BEFORE UPDATE OF status ON goals
            BEGIN
                SELECT RAISE(ABORT, 'completion failed');
            END;
        """)
        with pytest.raises(GoalStorageError):
            api.complete_goal(
                child,
                1,
                completion_grant_id=grant["id"],
                rationale="Reviewed",
                evidence_ids=[report["evidence_id"]],
            )
        assert db.execute(
            "SELECT count(*) FROM goal_events WHERE kind = 'completion'"
        ).fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM completion_citations").fetchone() == (
            0,
        )
    assert api.get_goal(child)["status"] == "active"
    history = api.get_goal_history(child)[0]
    assert history["completion"] is None and history["evidence"] == [report]
