import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from importlib.resources import files
from threading import Barrier

import pytest

from harness_api import (
    GoalAPI,
    GoalNotFoundError,
    GoalStorageError,
    GoalValidationError,
)


def test_create_read_update_and_delete_goal(tmp_path):
    path = tmp_path / "workspace" / "goals.sqlite3"
    api = GoalAPI(path)

    draft = api.create_goal(
        "Review notes",
        desired_outcome="Find the next step",
        duration="one_time",
        assessment_type="judgment",
        success_criteria="The engineer understands the handover",
        measurement_plan="Ask the engineer for feedback",
    )
    goal_id = draft["id"]
    assert draft["status"] == "draft"
    assert draft["revision"] == 1
    assert GoalAPI(path).get_goal(goal_id) == draft
    assert api.list_goals("active") == []

    updated = api.update_goal(goal_id, title="Review project notes")
    assert updated["revision"] == 2
    assert updated["desired_outcome"] == "Find the next step"
    assert updated["duration"] == "one_time"
    assert updated["assessment_type"] == "judgment"
    assert updated["success_criteria"] == draft["success_criteria"]
    assert updated["measurement_plan"] == draft["measurement_plan"]
    assert api.update_goal(goal_id, title=updated["title"]) == updated
    assert api.update_goal(goal_id, desired_outcome=None)["revision"] == 3
    assert api.list_goals()[0]["title"] == "Review project notes"

    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        connection.executescript("""
            INSERT INTO operators (id, owner_user_id, name) VALUES (1, 'local', 'Alice');
            INSERT INTO goal_assignments (goal_id, operator_id) VALUES (1, 1);
            """)
        assert api.get_goal(goal_id)["operator"] == "Alice"

        api.delete_goal(goal_id)
        assert api.list_goals() == []
        with pytest.raises(GoalNotFoundError):
            api.get_goal(goal_id)
        with pytest.raises(GoalNotFoundError):
            api.update_goal(goal_id, title="Another title")

        history = connection.execute(
            "SELECT title FROM goal_revisions WHERE goal_id = ? ORDER BY revision",
            (goal_id,),
        ).fetchall()
        assert history == [
            ("Review notes",),
            ("Review project notes",),
            ("Review project notes",),
        ]
        assert connection.execute(
            "SELECT released_at IS NOT NULL FROM goal_assignments WHERE goal_id = ?",
            (goal_id,),
        ).fetchone() == (1,)

    assert api.create_goal("Another goal")["id"] > goal_id


def test_migrates_existing_database_and_limits_operations_to_local_user(tmp_path):
    path = tmp_path / "goals.sqlite3"
    original_schema = files("harness_api").joinpath("migrations/001_initial.sql")
    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        connection.executescript(original_schema.read_text(encoding="utf-8"))
        connection.executescript("""
            INSERT INTO users (id, display_name) VALUES ('other', 'Other user');
            INSERT INTO goals (id, owner_user_id, status)
                VALUES (12, 'local', 'active'), (13, 'other', 'active');
            INSERT INTO goal_revisions (goal_id, revision, title)
                VALUES (12, 1, 'Saved goal'), (13, 1, 'Other user goal');
            """)

    api = GoalAPI(path)
    assert [goal["id"] for goal in api.list_goals()] == [12]
    assert api.get_goal(12)["title"] == "Saved goal"
    assert api.get_goal(12)["parent_goal_id"] is None
    assert api.get_goal(12)["duration_days"] is None
    with pytest.raises(GoalNotFoundError):
        api.create_goal("Child", parent_goal_id=13)
    with pytest.raises(GoalNotFoundError):
        api.get_goal(13)
    with pytest.raises(GoalNotFoundError):
        api.update_goal(13, title="Another title")
    with pytest.raises(GoalNotFoundError):
        api.delete_goal(13)
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (4,)
        assert connection.execute(
            "SELECT deleted_at FROM goals WHERE id = 13"
        ).fetchone() == (None,)


def test_identical_completion_returns_original_decision(tmp_path):
    path = tmp_path / "goals.sqlite3"
    api = GoalAPI(path)
    goal = api.create_goal("Review notes")
    ready = Barrier(2, timeout=5)

    def complete():
        other = GoalAPI(path)
        ready.wait()
        return other.complete_goal(goal["id"], 1, confirmation="I reviewed the notes")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, retry = [pool.submit(complete) for _ in range(2)]
        decision = first.result()
        assert retry.result() == decision
    assert (
        api.complete_goal(goal["id"], 1, confirmation="I reviewed the notes")
        == decision
    )
    with pytest.raises(GoalValidationError, match="different completion"):
        api.complete_goal(goal["id"], 1, reference="I reviewed the notes")
    assert api.get_goal(goal["id"])["status"] == "completed"
    assert decision["recorded_by"] == "local"
    assert decision["evidence_kind"] == "owner_confirmation"
    assert decision["recorded_at"] and decision["event_id"]
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute(
            "SELECT count(*) FROM goal_events WHERE kind='completion'"
        ).fetchone() == (1,)


def test_stale_completion_cannot_complete_a_revised_goal(tmp_path):
    api = GoalAPI(tmp_path / "goals.sqlite3")
    root = api.create_goal("Root", status="active")
    child = api.create_goal("Track", parent_goal_id=root["id"], duration_days=7)
    sibling = api.create_goal("Sibling", parent_goal_id=root["id"])
    evidence = "tracker-app:entry/123"
    decision = api.complete_goal(child["id"], 1, reference=evidence)
    assert decision["evidence_kind"] == "owner_supplied_reference"
    assert decision["recorded_by"] == "local" and decision["evidence"] == evidence
    revised = api.update_goal(child["id"], duration_days=14)
    with pytest.raises(GoalValidationError, match="Stale revision"):
        api.complete_goal(child["id"], 1, reference=evidence)
    assert api.get_goal(child["id"]) == revised
    assert revised["revision"] == 2 and revised["status"] == "active"
    assert revised["completion"] is None
    history = api.get_goal_history(child["id"])
    assert [(r["duration_days"], r["completion"]) for r in history] == [
        (7, decision),
        (14, None),
    ]
    assert api.get_goal(root["id"]) == root
    assert api.get_goal(sibling["id"]) == sibling


@pytest.mark.parametrize("status", ["paused", "revoked"])
def test_completion_respects_stored_status(tmp_path, status):
    path = tmp_path / "goals.sqlite3"
    api = GoalAPI(path)
    goal = api.create_goal("Test")
    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        connection.execute(
            "UPDATE goals SET status = ? WHERE id = ?", (status, goal["id"])
        )
    if status == "paused":
        api.complete_goal(goal["id"], 1, confirmation="Verified")
        assert api.get_goal(goal["id"])["status"] == "completed"
    else:
        with pytest.raises(GoalValidationError, match="revoked"):
            api.complete_goal(goal["id"], 1, confirmation="Verified")
        assert api.get_goal(goal["id"])["completion"] is None


def test_goal_titles_are_validated_across_model_writes(tmp_path):
    api = GoalAPI(tmp_path / "goals.sqlite3")
    with pytest.raises(GoalValidationError, match="A goal title is required"):
        api.create_goal(" \t")

    goal = api.create_goal(" Review the handover ")
    assert goal["title"] == "Review the handover"
    with pytest.raises(GoalValidationError, match="A goal title is required"):
        api.update_goal(goal["id"], title="\n")
    assert api.get_goal(goal["id"]) == goal


def test_invalid_ids_and_revisions_cannot_select_an_existing_goal(tmp_path):
    api = GoalAPI(tmp_path / "goals.sqlite3")
    goal = api.create_goal("Review notes")
    with pytest.raises(GoalValidationError, match="Revision"):
        api.complete_goal(goal["id"], True, confirmation="Verified")
    with pytest.raises(GoalValidationError, match="Goal ID"):
        api.delete_goal(True)
    with pytest.raises(GoalValidationError, match="Goal ID"):
        api.create_goal("Child", parent_goal_id=2**63)
    with pytest.raises(GoalValidationError, match="Goal ID"):
        api.get_goal_tree(2**63)
    assert api.get_goal(goal["id"]) == goal
    assert len(api.list_goals()) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"assessment_type": "unknown"},
        {"duration": "weekly"},
        {"duration_days": -1},
    ],
)
def test_invalid_definition_returns_validation_error_without_writing(tmp_path, changes):
    api = GoalAPI(tmp_path / "goals.sqlite3")
    goal = api.create_goal("Log meals", duration_days=7)
    with pytest.raises(GoalValidationError):
        api.create_goal("Invalid", **changes)
    with pytest.raises(GoalValidationError):
        api.update_goal(goal["id"], **changes)
    assert api.get_goal(goal["id"]) == goal
    assert len(api.list_goals()) == 1


def test_failed_status_update_rolls_back_completion_evidence(tmp_path):
    path = tmp_path / "goals.sqlite3"
    api = GoalAPI(path)
    goal = api.create_goal("Review notes")
    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        connection.executescript("""
            CREATE TRIGGER fail_status BEFORE UPDATE OF status ON goals BEGIN
                SELECT RAISE(ABORT, 'test failure');
            END;
            """)
        with pytest.raises(GoalStorageError):
            api.complete_goal(goal["id"], 1, reference="notes:review/1")
        assert connection.execute("SELECT count(*) FROM goal_events").fetchone() == (0,)
    assert api.get_goal(goal["id"]) == goal


def test_opening_current_database_does_not_wait_for_writer(tmp_path):
    path = tmp_path / "goals.sqlite3"
    GoalAPI(path).create_goal("Review the handover")
    with closing(sqlite3.connect(path, autocommit=True)) as writer:
        writer.execute("BEGIN IMMEDIATE")
        assert GoalAPI(path).list_goals()[0]["title"] == "Review the handover"


def test_storage_failure_rolls_back_goal_and_revision(tmp_path):
    path = tmp_path / "goals.sqlite3"
    api = GoalAPI(path)
    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        connection.executescript("""
            CREATE TRIGGER fail_event_insert BEFORE INSERT ON goal_events
            BEGIN
                SELECT RAISE(ABORT, 'test failure');
            END;
            """)

    with pytest.raises(GoalStorageError, match="The goals database is unavailable"):
        api.create_goal("Review the handover", original_message="Save this goal")
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM goals").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM goal_revisions").fetchone() == (
            0,
        )
