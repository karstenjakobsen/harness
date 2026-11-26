import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier

import pytest

from harness_api import GoalAPI, UserAPI, WorkspaceStorageError


def test_generated_keys_and_integer_foreign_keys(tmp_path):
    path = tmp_path / "workspace.db"
    users = UserAPI(path)
    user = users.create_user("9000")
    assert type(user["id"]) is int and user["id"] != 9000
    assert user["username"] == "9000"
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.execute("PRAGMA foreign_keys = ON")
        for table in ("users", "operators", "goals", "goal_assignments", "goal_events"):
            (ddl,) = db.execute(
                "SELECT sql FROM sqlite_schema WHERE name = ?", (table,)
            ).fetchone()
            assert "INTEGER PRIMARY KEY AUTOINCREMENT" in ddl
        for table, strict in db.execute(
            "SELECT name, strict FROM pragma_table_list WHERE schema='main' AND name NOT GLOB 'sqlite_*'"
        ):
            assert strict == 1
            types = {
                row[1]: row[2]
                for row in db.execute("SELECT * FROM pragma_table_info(?)", (table,))
            }
            foreign_keys = list(
                db.execute("SELECT * FROM pragma_foreign_key_list(?)", (table,))
            )
            for fk in foreign_keys:
                assert types[fk[3]] == "INTEGER"
            keys = {col for col in types if col.endswith("_id")}
            if table == "run_calls":
                # The requested target can be absent. The audit still keeps its ID.
                assert types["target_run_id"] == "INTEGER"
                keys.remove("target_run_id")
                assert types["target_skill_id"] == "TEXT"
                keys.remove("target_skill_id")
            assert keys <= {fk[3] for fk in foreign_keys}
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM users WHERE id = 1")
        db.execute("DELETE FROM users WHERE id = ?", (user["id"],))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO operators(owner_user_id, name) VALUES (?, 'missing')",
                (user["id"],),
            )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO goals(owner_user_id) VALUES ('not a key')")
    assert users.create_user("second")["id"] > user["id"]


def test_concurrent_first_use_initializes_one_unversioned_workspace(tmp_path):
    path = tmp_path / "workspace.db"
    ready = Barrier(4)

    def create_user(number):
        ready.wait(timeout=10)
        return UserAPI(path).create_user(f"user-{number}")["id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(create_user, range(4)))

    assert sorted(ids) == [2, 3, 4, 5]
    assert {user["id"] for user in UserAPI(path).list_users()} == {1, *ids}
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (0,)


def test_failed_initialization_can_retry_from_an_empty_database(tmp_path, monkeypatch):
    path = tmp_path / "workspace.db"
    (tmp_path / "schema.sql").write_text(
        "CREATE TABLE users(id INTEGER); INSERT INTO missing VALUES (1);"
    )
    with monkeypatch.context() as patch:
        patch.setattr("harness_api.database.files", lambda package: tmp_path)
        with pytest.raises(WorkspaceStorageError):
            UserAPI(path)

    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT name FROM sqlite_schema").fetchall() == []
    assert [user["username"] for user in UserAPI(path).list_users()] == ["admin"]


def test_sqlite_enforces_the_goal_revision_and_event_roles_of_a_decision(tmp_path):
    path = tmp_path / "workspace.db"
    api = GoalAPI(path, local_owner=False)
    goal = api.create_goal("Review")["id"]
    other = api.create_goal("Other")["id"]
    report = api.record_observation(other, confirmation="Reviewed", retry_key="once")
    earlier = api.record_observation(goal, confirmation="Started", retry_key="first")
    api.update_goal(goal, title="Review again")
    decision = api.complete_goal(
        goal, 2, confirmation="Complete", evidence_ids=[earlier["evidence_id"]]
    )
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            db.execute(
                "INSERT INTO completion_citations(goal_id, decision_id, evidence_id) VALUES (?, ?, ?)",
                (goal, decision["event_id"], report["evidence_id"]),
            )
        # Additional citations may refer to earlier revisions. The decision's own statement
        # must belong to the goal and revision it completed.
        for invalid_statement in (
            earlier["evidence_id"],
            report["evidence_id"],
            decision["event_id"],
        ):
            with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
                db.execute(
                    "UPDATE goal_events SET statement_evidence_id = ? WHERE id = ?",
                    (invalid_statement, decision["event_id"]),
                )
        # Valid event IDs on the same goal must also have the right roles.
        for decision_id, evidence_id in [
            (decision["statement_evidence_id"], decision["statement_evidence_id"]),
            (decision["event_id"], decision["event_id"]),
        ]:
            with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
                db.execute(
                    "INSERT INTO completion_citations(goal_id, decision_id, evidence_id) VALUES (?, ?, ?)",
                    (goal, decision_id, evidence_id),
                )
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert GoalAPI(path).get_goal(goal)["completion"] == decision


def test_sqlite_enforces_retry_uniqueness_for_unknown_submitters(tmp_path):
    path = tmp_path / "workspace.db"
    api = GoalAPI(path, local_owner=False)
    goal = api.create_goal("Review")["id"]
    report = api.record_observation(goal, confirmation="Reviewed", retry_key="once")
    with (
        closing(sqlite3.connect(path, autocommit=True)) as db,
        pytest.raises(sqlite3.IntegrityError, match="UNIQUE"),
    ):
        db.execute(
            """INSERT INTO goal_events(goal_id, revision, kind, actor_user_id, retry_key, payload)
               SELECT goal_id, revision, kind, actor_user_id, retry_key, payload
               FROM goal_events WHERE id = ?""",
            (report["evidence_id"],),
        )


def test_write_to_missing_workspace_does_not_recreate_the_file(tmp_path):
    path = tmp_path / "workspace.db"
    users = UserAPI(path)
    path.rename(tmp_path / "moved.db")
    with pytest.raises(WorkspaceStorageError):
        users.create_user("sam")
    assert not path.exists()
