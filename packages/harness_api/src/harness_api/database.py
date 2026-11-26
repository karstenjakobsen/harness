import sqlite3
from collections.abc import Generator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Literal

DATABASE_PATH = Path(".harness/goals.sqlite3")
ADMIN_USER_ID = 1


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
    """Initialize an empty local workspace and manage transactional connections."""

    storage_error = WorkspaceStorageError

    def __init__(self, path: Path | str = DATABASE_PATH) -> None:
        self._path = Path(path).absolute()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise self.storage_error() from error
        with self._connection("rwc") as connection:
            has_schema = (
                "SELECT 1 FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*' LIMIT 1"
            )
            if connection.execute(has_schema).fetchone():
                return
            connection.execute("BEGIN IMMEDIATE")
            # Another process may have initialized the database while we waited.
            if not connection.execute(has_schema).fetchone():
                schema = (
                    files("harness_api")
                    .joinpath("schema.sql")
                    .read_text(encoding="utf-8")
                )
                connection.executescript(schema)
            connection.execute("COMMIT")

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
