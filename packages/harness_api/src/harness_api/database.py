import sqlite3
from collections.abc import Generator
from contextlib import closing, contextmanager
from importlib.resources import files
from pathlib import Path
from typing import Literal

DATABASE_PATH = Path(".harness/goals.sqlite3")
ADMIN_USER_ID = 1
SCHEMA_VERSION = 7


class WorkspaceStorageError(RuntimeError):
    def __init__(self, message: str = "The workspace database is unavailable.") -> None:
        super().__init__(message)


class WorkspaceDatabase:
    """Fresh-workspace schema and transactional connections shared by the APIs."""

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
            if (
                version
                or connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*' LIMIT 1"
                ).fetchone()
            ):
                raise self.storage_error(
                    f"Cannot open workspace schema version {version}. "
                    f"Schema version {SCHEMA_VERSION} requires a fresh database."
                )
            snapshot = files("harness_api").joinpath("migrations", "001_initial.sql")
            connection.executescript(snapshot.read_text(encoding="utf-8"))

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
