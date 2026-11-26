import sqlite3
from contextlib import closing

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


def test_assignment_records_responsibility_without_granting_completion(workspace):
    path, _, _, _, child, operator_id, report = workspace
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        assignment = db.execute(
            "INSERT INTO goal_assignments (goal_id, operator_id) VALUES (?, ?) RETURNING id",
            (child, operator_id),
        ).fetchone()[0]

    api = GoalAPI(path)
    assert api.get_goal(child)["operator"] == "Reviewer"
    history = api.get_goal_history(child)
    request = {
        "rationale": "Verified by the owner",
        "evidence_ids": [report["evidence_id"]],
    }
    with pytest.raises(GoalValidationError, match="grant"):
        api.start_run(completion_grant_id=assignment)
    with pytest.raises(GoalValidationError, match="grant"):
        api.complete_goal(child, 1, completion_grant_id=assignment, **request)
    assert api.get_goal_history(child) == history
    grant = api.grant_completion(child, operator_id)
    assert grant["id"] != assignment
    decision = api.complete_goal(child, 1, completion_grant_id=grant["id"], **request)
    assert decision["recorded_by_operator_id"] == operator_id
    assert decision["evidence_ids"] == [report["evidence_id"]]


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
