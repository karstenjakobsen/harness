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
    assert admin["id"] == admin["display_name"] == "admin"
    with pytest.raises(AccountConflictError, match="admin cannot be deleted"):
        users.delete_user("admin")

    owner = users.create_user("lee")
    assert owner["id"] == owner["display_name"] == "lee"
    with pytest.raises(AccountConflictError):
        users.create_user("lee")
    with pytest.raises(AccountNotFoundError):
        operators.register_operator("Coach", "missing")
    first = operators.register_operator("Coach", "lee", mission="Review logs")
    second = operators.register_operator("Planner", "lee")
    default = operators.register_operator("Default")
    assert default["owner_user_id"] == "admin"
    assert [first, second] == operators.list_operators("lee")
    assert first["owner_user_id"] == "lee" and first["mission"] == "Review logs"
    renamed = users.update_user("lee", "Lee Smith")
    assert users.get_user("lee") == {**owner, "display_name": "Lee Smith"} == renamed
    retained = []
    for registered in (first, second):
        with pytest.raises(AccountConflictError, match="registered operator"):
            users.delete_user("lee")
        assert users.get_user("lee") == renamed
        removed = operators.unregister_operator(registered["id"])
        assert removed == {**registered, "deleted_at": removed["deleted_at"]}
        assert removed["deleted_at"]
        retained.append((removed["id"], removed["deleted_at"]))
        with pytest.raises(AccountNotFoundError):
            operators.get_operator(registered["id"])
        with pytest.raises(AccountNotFoundError):
            operators.unregister_operator(registered["id"])

    deleted = users.delete_user("lee")
    assert deleted["deleted_at"]
    assert UserAPI(path).list_users() == [admin]
    assert OperatorAPI(path).list_operators() == [default]
    with pytest.raises(AccountNotFoundError):
        users.get_user("lee")
    with pytest.raises(AccountNotFoundError):
        users.update_user("lee", "New name")
    with pytest.raises(AccountNotFoundError):
        operators.register_operator("New coach", "lee")
    with pytest.raises(AccountConflictError):
        users.create_user("lee")
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute(
            """SELECT user.display_name, user.deleted_at, operator.id, operator.deleted_at
               FROM users AS user JOIN operators AS operator ON operator.owner_user_id = user.id
               WHERE user.id = 'lee' ORDER BY operator.id"""
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
        users.update_user("admin", "  ")
    with pytest.raises(AccountValidationError):
        operators.register_operator("  ")
    with pytest.raises(AccountValidationError):
        operators.unregister_operator(True)
    assert operators.list_operators() == []
    assert users.get_user("admin")["display_name"] == "admin"


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


@pytest.fixture
def legacy_workspace(legacy_database):
    path = legacy_database(4)
    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript("""
            INSERT INTO operators (id, owner_user_id, name) VALUES (9, 'local', 'Coach');
            INSERT INTO goals (id, owner_user_id, status) VALUES (4, 'local', 'completed');
            INSERT INTO goal_revisions (goal_id, revision, title) VALUES (4, 1, 'Review logs');
            INSERT INTO goal_assignments (goal_id, operator_id) VALUES (4, 9);
            INSERT INTO goal_events (id, goal_id, revision, kind, actor, payload)
                VALUES (22, 4, 1, 'completion', 'local',
                  '{"evidence_kind":"owner_confirmation","evidence":"Reviewed"}');
        """)
    return path


def test_migrates_legacy_owner_assignments_and_completion_once(legacy_workspace):
    operators = OperatorAPI(legacy_workspace)
    assert operators.get_operator(9)["owner_user_id"] == "admin"
    goals = GoalAPI(legacy_workspace)
    goal = goals.get_goal(4)
    assert goal["operator"] == "Coach" and goal["status"] == "completed"
    completion = goals.complete_goal(4, 1, confirmation="Reviewed")
    assert completion == goal["completion"]
    assert completion["event_id"] == 22 and completion["recorded_by"] == "admin"
    with closing(sqlite3.connect(legacy_workspace)) as connection:
        assert connection.execute("SELECT id FROM users").fetchall() == [("admin",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_standalone_snapshot_initializes_workspace(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    snapshot = files("harness_api").joinpath("migrations", "001_initial.sql")
    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        connection.executescript(snapshot.read_text(encoding="utf-8"))
        assert connection.execute("PRAGMA user_version").fetchone() == (5,)
    assert [user["id"] for user in UserAPI(path).list_users()] == ["admin"]
    assert OperatorAPI(path).register_operator("Coach")["owner_user_id"] == "admin"
    goals = GoalAPI(path)
    goal = goals.create_goal("Review logs", duration_days=7)
    assert (
        goals.complete_goal(goal["id"], 1, confirmation="Reviewed")["recorded_by"]
        == "admin"
    )


def test_failed_snapshot_rolls_back_legacy_schema_and_data(legacy_database):
    path = legacy_database(3)
    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        connection.executescript("""
            INSERT INTO goals (id, owner_user_id) VALUES (4, 'local');
            INSERT INTO goal_revisions (goal_id, revision, title) VALUES (4, 1, 'Review logs');
            INSERT INTO goal_events (goal_id, revision, kind, actor, payload)
                VALUES (4, 1, 'completion', 'local', '{}'), (4, 1, 'completion', 'local', '{}');
        """)
        with pytest.raises(WorkspaceStorageError, match="UNIQUE"):
            UserAPI(path)
        assert connection.execute("PRAGMA user_version").fetchone() == (3,)
        assert connection.execute("SELECT id FROM users").fetchall() == [("local",)]
        assert connection.execute("SELECT owner_user_id FROM goals").fetchall() == [
            ("local",)
        ]
        assert connection.execute("SELECT actor FROM goal_events").fetchall() == [
            ("local",),
            ("local",),
        ]
        assert "deleted_at" not in {
            row[1] for row in connection.execute("PRAGMA table_info(users)")
        }


def test_migration_preserves_distinct_accounts_if_admin_id_is_taken(legacy_workspace):
    with closing(sqlite3.connect(legacy_workspace, autocommit=True)) as connection:
        connection.execute(
            "INSERT INTO users (id, display_name) VALUES ('admin', 'Another owner')"
        )
        with pytest.raises(WorkspaceStorageError, match="existing admin user ID"):
            UserAPI(legacy_workspace)
        assert connection.execute("PRAGMA user_version").fetchone() == (4,)
        assert connection.execute(
            "SELECT id, display_name FROM users ORDER BY id"
        ).fetchall() == [("admin", "Another owner"), ("local", "Local user")]
        assert connection.execute("SELECT owner_user_id FROM operators").fetchone() == (
            "local",
        )
