import sqlite3
from contextlib import closing
from importlib.resources import files

import pytest

from harness_api import (
    AccountConflictError,
    AccountNotFoundError,
    AccountValidationError,
    GoalAPI,
    OperatorAPI,
    UserAPI,
    WorkspaceStorageError,
)


def test_user_owns_registered_operators_and_keeps_history_after_deletion(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    users = UserAPI(path)
    operators = OperatorAPI(path)
    (admin,) = users.list_users()
    assert admin["id"] == 1
    assert admin["username"] == admin["display_name"] == "admin"
    with pytest.raises(AccountConflictError, match="admin cannot be deleted"):
        users.delete_user(1)

    with pytest.raises(AccountConflictError):
        users.create_user("admin")

    owner = users.create_user("lee")
    owner_id = owner["id"]
    assert owner["username"] == owner["display_name"] == "lee"
    with pytest.raises(AccountConflictError):
        users.create_user("lee")
    with pytest.raises(AccountNotFoundError):
        operators.register_operator("Coach", 999)
    first = operators.register_operator("Coach", owner_id, mission="Review logs")
    second = operators.register_operator("Planner", owner_id)
    default = operators.register_operator("Default")
    assert default["owner_user_id"] == 1
    assert [first, second] == operators.list_operators(owner_id)
    assert first["owner_user_id"] == owner_id and first["mission"] == "Review logs"
    renamed = users.update_user(owner_id, "Lee Smith")
    assert users.get_user(owner_id) == {**owner, "display_name": "Lee Smith"} == renamed
    retained = []
    for registered in (first, second):
        with pytest.raises(AccountConflictError, match="registered operator"):
            users.delete_user(owner_id)
        assert users.get_user(owner_id) == renamed
        removed = operators.unregister_operator(registered["id"])
        assert removed == {**registered, "deleted_at": removed["deleted_at"]}
        assert removed["deleted_at"]
        retained.append((removed["id"], removed["deleted_at"]))
        with pytest.raises(AccountNotFoundError):
            operators.get_operator(registered["id"])
        with pytest.raises(AccountNotFoundError):
            operators.unregister_operator(registered["id"])

    deleted = users.delete_user(owner_id)
    assert deleted["deleted_at"]
    assert UserAPI(path).list_users() == [admin]
    assert OperatorAPI(path).list_operators() == [default]
    with pytest.raises(AccountNotFoundError):
        users.get_user(owner_id)
    with pytest.raises(AccountNotFoundError):
        users.update_user(owner_id, "New name")
    with pytest.raises(AccountNotFoundError):
        operators.register_operator("New coach", owner_id)
    with pytest.raises(AccountConflictError):
        users.create_user("lee")
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute(
            """SELECT user.display_name, user.deleted_at, operator.id, operator.deleted_at
               FROM users AS user JOIN operators AS operator ON operator.owner_user_id = user.id
               WHERE user.id = ? ORDER BY operator.id""",
            (owner_id,),
        ).fetchall() == [
            ("Lee Smith", deleted["deleted_at"], operator_id, unregistered_at)
            for operator_id, unregistered_at in retained
        ]


def test_unregister_releases_only_open_assignments_and_retains_operator(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    operators = OperatorAPI(path)
    goals = GoalAPI(path)
    operator = operators.register_operator("Coach")
    other = operators.register_operator("Planner")
    goal = goals.create_goal("Review logs")["id"]
    other_goal = goals.create_goal("Plan the week")["id"]
    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        connection.executemany(
            "INSERT INTO goal_assignments (goal_id, operator_id, released_at) VALUES (?, ?, ?)",
            [
                (goal, operator["id"], "2025-01-01"),
                (goal, operator["id"], None),
                (other_goal, other["id"], None),
            ],
        )
        assert goals.get_goal(goal)["operator"] == "Coach"
        removed = operators.unregister_operator(operator["id"])
        assert goals.get_goal(goal)["operator"] is None
        assert goals.get_goal(other_goal)["operator"] == "Planner"
        assert connection.execute(
            "SELECT operator_id, released_at FROM goal_assignments ORDER BY id"
        ).fetchall() == [
            (operator["id"], "2025-01-01"),
            (operator["id"], removed["deleted_at"]),
            (other["id"], None),
        ]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_validation_prevents_invalid_registration_and_user_changes(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    users, operators = UserAPI(path), OperatorAPI(path)
    with pytest.raises(AccountValidationError):
        users.create_user("  ")
    with pytest.raises(AccountValidationError):
        users.update_user(1, "  ")
    with pytest.raises(AccountValidationError):
        operators.register_operator("  ")
    with pytest.raises(AccountValidationError):
        operators.unregister_operator(True)
    assert operators.list_operators() == []
    assert users.get_user(1)["display_name"] == "admin"


def test_failed_assignment_release_leaves_operator_registered(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    operators = OperatorAPI(path)
    operator = operators.register_operator("Coach")
    goal_id = GoalAPI(path).create_goal("Review logs")["id"]
    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        connection.execute(
            "INSERT INTO goal_assignments (goal_id, operator_id) VALUES (?, ?)",
            (goal_id, operator["id"]),
        )
        connection.executescript("""
            CREATE TRIGGER fail_release BEFORE UPDATE OF released_at ON goal_assignments
            BEGIN
                SELECT RAISE(ABORT, 'release failed');
            END;
        """)
        with pytest.raises(WorkspaceStorageError):
            operators.unregister_operator(operator["id"])
        assert connection.execute(
            "SELECT released_at FROM goal_assignments"
        ).fetchone() == (None,)
    assert operators.get_operator(operator["id"]) == operator


def test_standalone_snapshot_initializes_workspace(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    snapshot = files("harness_api").joinpath("migrations", "001_initial.sql")
    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        connection.executescript(snapshot.read_text(encoding="utf-8"))
        assert connection.execute("PRAGMA user_version").fetchone() == (7,)
    assert [user["id"] for user in UserAPI(path).list_users()] == [1]
    assert OperatorAPI(path).register_operator("Coach")["owner_user_id"] == 1
    goals = GoalAPI(path)
    goal = goals.create_goal("Review logs", duration_days=7)
    assert (
        goals.complete_goal(goal["id"], 1, confirmation="Reviewed")["recorded_by"] == 1
    )
