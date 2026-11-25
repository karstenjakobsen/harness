import sqlite3
from collections.abc import Generator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Literal

DATABASE_PATH = Path(".harness/goals.sqlite3")
ADMIN_USER_ID = 1
SCHEMA_VERSION = 9


def utc_timestamp() -> str:
    return (
        datetime.now(UTC)
        .replace(tzinfo=None)
        .isoformat(sep=" ", timespec="microseconds")
    )


class WorkspaceStorageError(RuntimeError):
    def __init__(self, message: str = "The workspace database is unavailable.") -> None:
        super().__init__(message)


class WorkspaceDatabase:
    """Workspace schema setup, upgrades and transactional connections."""

    storage_error = WorkspaceStorageError

    def __init__(self, path: Path | str = DATABASE_PATH) -> None:
        self._path = Path(path).absolute()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise self.storage_error() from error
        with self._connection("rwc") as connection:
            if (
                connection.execute("PRAGMA user_version").fetchone()[0]
                == SCHEMA_VERSION
            ):
                return

        with self._write() as connection:
            (version,) = connection.execute("PRAGMA user_version").fetchone()
            if version == SCHEMA_VERSION:
                return
            if version not in (0, 7, 8) or (
                version == 0
                and connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*' LIMIT 1"
                ).fetchone()
            ):
                raise self.storage_error(
                    f"Cannot open workspace schema version {version}. "
                    f"Use a version 7 or 8 workspace or a fresh database for schema version {SCHEMA_VERSION}."
                )
            snapshot = (
                files("harness_api")
                .joinpath("migrations", "001_initial.sql")
                .read_text(encoding="utf-8")
            )
            if version == 0:
                connection.executescript(snapshot)
                return
            if version == 7:
                self._upgrade_v7(connection, snapshot)
            self._upgrade_v8(connection, snapshot)

    @staticmethod
    def _upgrade_v7(connection: sqlite3.Connection, snapshot: str) -> None:
        # Rebuild the two related tables to widen the completion constraint. SQLite
        # keeps the old foreign keys attached to the renamed tables during the copy.
        connection.executescript("""
            ALTER TABLE goal_assignments ADD COLUMN completion_granted_at TEXT;
            ALTER TABLE goal_assignments ADD COLUMN completion_grant_id INTEGER
                AS (CASE WHEN completion_granted_at IS NOT NULL THEN id END);
            CREATE UNIQUE INDEX assignment_completion_grant
                ON goal_assignments(goal_id, completion_grant_id);
            ALTER TABLE completion_citations RENAME TO v7_completion_citations;
            ALTER TABLE goal_events RENAME TO v7_goal_events;
            DROP INDEX one_completion_per_revision;
            DROP INDEX observation_retry;
            DROP INDEX observations_by_goal;
        """)
        event_schema = snapshot.split("-- Begin goal event schema\n", 1)[1].split(
            "-- End goal event schema\n", 1
        )[0]
        connection.executescript(event_schema)
        connection.executescript("""
            INSERT INTO goal_events (
                id, goal_id, revision, kind, actor_user_id, message_role,
                occurred_at, recorded_at, payload, retry_key, statement_evidence_id
            )
            SELECT id, goal_id, revision, kind, actor_user_id, message_role,
                   occurred_at, recorded_at, payload, retry_key, statement_evidence_id
            FROM v7_goal_events;
            INSERT INTO completion_citations (goal_id, decision_id, evidence_id)
            SELECT goal_id, decision_id, evidence_id FROM v7_completion_citations;
            DELETE FROM sqlite_sequence WHERE name = 'goal_events';
            UPDATE sqlite_sequence SET name = 'goal_events' WHERE name = 'v7_goal_events';
            DROP TABLE v7_completion_citations;
            DROP TABLE v7_goal_events;
            PRAGMA user_version = 8;
        """)

    @staticmethod
    def _upgrade_v8(connection: sqlite3.Connection, snapshot: str) -> None:
        activity_schema = snapshot.split("-- Begin run activity schema\n", 1)[1].split(
            "-- End run activity schema\n", 1
        )[0]
        connection.executescript(activity_schema + "PRAGMA user_version = 9;")

    @contextmanager
    def _connection(
        self, mode: Literal["ro", "rw", "rwc"]
    ) -> Generator[sqlite3.Connection]:
        uri = f"{self._path.as_uri()}?mode={mode}"
        try:
            with closing(sqlite3.connect(uri, uri=True, autocommit=True)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON")
                yield connection
        except (OSError, sqlite3.Error) as error:
            raise self.storage_error() from error

    @contextmanager
    def _write(self) -> Generator[sqlite3.Connection]:
        with self._connection("rw") as connection:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
