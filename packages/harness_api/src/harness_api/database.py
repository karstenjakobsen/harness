import sqlite3
from collections.abc import Generator
from contextlib import closing, contextmanager
from importlib.resources import files
from pathlib import Path

DATABASE_PATH = Path(".harness/goals.sqlite3")
ADMIN_USER_ID = "admin"
SCHEMA_VERSION = 5


class WorkspaceStorageError(RuntimeError):
    def __init__(self, message: str = "The workspace database is unavailable.") -> None:
        super().__init__(message)


class WorkspaceDatabase:
    """Migrations and transactional connections shared by the workspace APIs."""

    storage_error = WorkspaceStorageError

    def __init__(self, path: Path | str = DATABASE_PATH) -> None:
        self._path = Path(path).absolute()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise self.storage_error() from error
        with self._connection() as connection:
            if (
                connection.execute("PRAGMA user_version").fetchone()[0]
                == SCHEMA_VERSION
            ):
                return

        with self._write() as connection:
            (version,) = connection.execute("PRAGMA user_version").fetchone()
            if version == SCHEMA_VERSION:
                return
            if not 0 <= version <= SCHEMA_VERSION:
                raise self.storage_error(
                    f"Unsupported workspace database version {version}."
                )
            snapshot = files("harness_api").joinpath("migrations", "001_initial.sql")
            try:
                if version:
                    self._upgrade_legacy_workspace(connection, version)
                connection.executescript(snapshot.read_text(encoding="utf-8"))
            except sqlite3.IntegrityError as error:
                raise self.storage_error(
                    f"Cannot apply workspace schema. {error}"
                ) from error

    def _upgrade_legacy_workspace(
        self, connection: sqlite3.Connection, version: int
    ) -> None:
        """Bring existing v1–v4 tables forward in place before applying the snapshot."""
        owners = connection.execute(
            "SELECT count(*) FROM users WHERE id IN ('local', 'admin')"
        ).fetchone()[0]
        if owners == 2:
            raise self.storage_error(
                "Resolve the existing admin user ID before migrating the local account."
            )

        if version < 2:
            connection.execute("ALTER TABLE goals ADD COLUMN deleted_at TEXT")
        if version < 3:
            connection.executescript("""
                ALTER TABLE goal_revisions ADD COLUMN duration TEXT
                    CHECK (duration IN ('one_time', 'standing'));
                ALTER TABLE goal_revisions ADD COLUMN assessment_type TEXT
                    CHECK (assessment_type IN ('objective', 'judgment', 'mixed'));
                ALTER TABLE goal_revisions ADD COLUMN success_criteria TEXT;
                ALTER TABLE goal_revisions ADD COLUMN measurement_plan TEXT;
            """)
        if version < 4:
            connection.executescript("""
                ALTER TABLE goals ADD COLUMN parent_goal_id INTEGER REFERENCES goals(id);
                ALTER TABLE goal_revisions ADD COLUMN duration_days INTEGER
                    CHECK (duration_days IS NULL OR (typeof(duration_days) = 'integer' AND duration_days > 0));
            """)
        connection.executescript("""
            ALTER TABLE users ADD COLUMN deleted_at TEXT CHECK (id != 'admin' OR deleted_at IS NULL);
            ALTER TABLE operators ADD COLUMN deleted_at TEXT;
            PRAGMA defer_foreign_keys = ON;
            UPDATE users SET id = 'admin', display_name = 'admin' WHERE id = 'local';
            UPDATE goals SET owner_user_id = 'admin' WHERE owner_user_id = 'local';
            UPDATE operators SET owner_user_id = 'admin' WHERE owner_user_id = 'local';
        """)
        if version >= 3:
            connection.execute("""
                UPDATE goal_events SET actor = 'admin'
                WHERE kind = 'completion' AND actor = 'local'
                  AND goal_id IN (SELECT id FROM goals WHERE owner_user_id = 'admin')
            """)

    @contextmanager
    def _connection(self, *, read_only: bool = False) -> Generator[sqlite3.Connection]:
        uri = self._path.as_uri() + ("?mode=ro" if read_only else "?mode=rwc")
        try:
            with closing(sqlite3.connect(uri, uri=True, autocommit=True)) as connection:
                connection.row_factory = sqlite3.Row
                yield connection
        except (OSError, sqlite3.Error) as error:
            raise self.storage_error() from error

    @contextmanager
    def _write(self) -> Generator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
