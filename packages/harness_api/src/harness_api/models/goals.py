import json
import sqlite3
from collections.abc import Generator
from contextlib import closing, contextmanager
from importlib.resources import files
from pathlib import Path
from types import EllipsisType
from typing import Literal, TypedDict

DATABASE_PATH = Path(".harness/goals.sqlite3")
LOCAL_USER_ID = "local"
MIGRATIONS = ("001_initial.sql", "002_goal_deletion.sql", "003_goal_definition.sql")

SELECT_GOALS = """
SELECT goal.id, goal.status, revision.title, revision.revision,
       revision.desired_outcome, revision.duration, revision.assessment_type,
       revision.success_criteria, revision.measurement_plan, operator.name AS operator
FROM goals AS goal
LEFT JOIN goal_revisions AS revision
    ON revision.goal_id = goal.id
    AND revision.revision = (
        SELECT MAX(revision) FROM goal_revisions WHERE goal_id = goal.id
    )
LEFT JOIN goal_assignments AS assignment
    ON assignment.goal_id = goal.id AND assignment.released_at IS NULL
LEFT JOIN operators AS operator
    ON operator.id = assignment.operator_id AND operator.owner_user_id = goal.owner_user_id
WHERE goal.owner_user_id = :owner AND goal.deleted_at IS NULL
"""

type GoalStatus = Literal["draft", "active", "paused", "completed", "revoked"]
type GoalDuration = Literal["one_time", "standing"]
type AssessmentType = Literal["objective", "judgment", "mixed"]


class GoalSummary(TypedDict):
    id: int
    status: GoalStatus
    title: str | None
    revision: int | None
    operator: str | None


class GoalDefinition(TypedDict):
    desired_outcome: str | None
    duration: GoalDuration | None
    assessment_type: AssessmentType | None
    success_criteria: str | None
    measurement_plan: str | None


class Goal(GoalSummary, GoalDefinition):
    pass


class GoalNotFoundError(LookupError):
    def __init__(self, goal_id: int) -> None:
        super().__init__(f"Goal {goal_id} was not found.")


class GoalValidationError(ValueError):
    """The requested goal definition is invalid."""


class GoalStorageError(RuntimeError):
    """The goal database could not be accessed."""

    def __init__(self) -> None:
        super().__init__("The goals database is unavailable.")


def _normalize_title(title: str) -> str:
    title = title.strip()
    if not title:
        raise GoalValidationError("A goal title is required.")
    return title


class GoalAPI:
    """SQLite-backed operations for the workspace's local user."""

    def __init__(self, path: Path | str = DATABASE_PATH) -> None:
        self._path = Path(path).absolute()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise GoalStorageError() from error
        with self._connection() as connection:
            if connection.execute("PRAGMA user_version").fetchone()[0] == len(
                MIGRATIONS
            ):
                return

        with self._write() as connection:
            (version,) = connection.execute("PRAGMA user_version").fetchone()
            if version > len(MIGRATIONS):
                raise RuntimeError(f"Unsupported goal database version {version}.")
            for filename in MIGRATIONS[version:]:
                migration = files("harness_api").joinpath("migrations", filename)
                connection.executescript(migration.read_text(encoding="utf-8"))

    def create_goal(
        self,
        title: str,
        *,
        desired_outcome: str | None = None,
        duration: GoalDuration | None = None,
        assessment_type: AssessmentType | None = None,
        success_criteria: str | None = None,
        measurement_plan: str | None = None,
        original_message: str | None = None,
        clarification: str | None = None,
    ) -> Goal:
        """Create a draft and its first definition in one transaction."""
        title = _normalize_title(title)
        definition = GoalDefinition(
            desired_outcome=desired_outcome,
            duration=duration,
            assessment_type=assessment_type,
            success_criteria=success_criteria,
            measurement_plan=measurement_plan,
        )
        with self._write() as connection:
            goal_id = connection.execute(
                "INSERT INTO goals (owner_user_id) VALUES (?) RETURNING id",
                (LOCAL_USER_ID,),
            ).fetchone()[0]
            self._add_revision(connection, goal_id, 1, title, definition)
            if original_message is not None:
                self._record_message(connection, goal_id, "user", original_message)
            if clarification is not None:
                self._record_message(connection, goal_id, "operator", clarification)
            return self._get_goal(connection, goal_id)

    def get_goal(self, goal_id: int) -> Goal:
        with self._connection(read_only=True) as connection:
            return self._get_goal(connection, goal_id)

    def list_goals(self, status: GoalStatus | None = None) -> list[GoalSummary]:
        with self._connection(read_only=True) as connection:
            rows = connection.execute(
                SELECT_GOALS
                + " AND (:status IS NULL OR goal.status = :status) ORDER BY goal.id",
                {"owner": LOCAL_USER_ID, "status": status},
            )
            return [self._summary(row) for row in rows]

    def update_goal(
        self,
        goal_id: int,
        *,
        title: str | None = None,
        desired_outcome: str | None | EllipsisType = ...,
    ) -> Goal:
        """Append a revision for a changed definition. Omit fields to keep their values."""
        with self._write() as connection:
            goal = self._get_goal(connection, goal_id)
            title = goal["title"] if title is None else _normalize_title(title)
            outcome = (
                goal["desired_outcome"] if desired_outcome is ... else desired_outcome
            )
            if (title, outcome) == (goal["title"], goal["desired_outcome"]):
                return goal
            if title is None:
                raise GoalValidationError("Add a title when updating an untitled goal.")
            definition = GoalDefinition(
                desired_outcome=outcome,
                duration=goal["duration"],
                assessment_type=goal["assessment_type"],
                success_criteria=goal["success_criteria"],
                measurement_plan=goal["measurement_plan"],
            )
            self._add_revision(
                connection, goal_id, (goal["revision"] or 0) + 1, title, definition
            )
            return self._get_goal(connection, goal_id)

    def delete_goal(self, goal_id: int) -> None:
        """Remove a goal from API reads while retaining its ID and history."""
        with self._write() as connection:
            result = connection.execute(
                """
                UPDATE goals SET deleted_at = CURRENT_TIMESTAMP
                WHERE id = ? AND owner_user_id = ? AND deleted_at IS NULL
                """,
                (goal_id, LOCAL_USER_ID),
            )
            if result.rowcount == 0:
                raise GoalNotFoundError(goal_id)
            connection.execute(
                """
                UPDATE goal_assignments SET released_at = CURRENT_TIMESTAMP
                WHERE goal_id = ? AND released_at IS NULL
                """,
                (goal_id,),
            )

    @contextmanager
    def _connection(self, *, read_only: bool = False) -> Generator[sqlite3.Connection]:
        uri = self._path.as_uri() + ("?mode=ro" if read_only else "?mode=rwc")
        try:
            with closing(sqlite3.connect(uri, uri=True, autocommit=True)) as connection:
                connection.row_factory = sqlite3.Row
                yield connection
        except (OSError, sqlite3.Error) as error:
            raise GoalStorageError() from error

    @contextmanager
    def _write(self) -> Generator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")

    def _get_goal(self, connection: sqlite3.Connection, goal_id: int) -> Goal:
        row = connection.execute(
            SELECT_GOALS + " AND goal.id = :id",
            {"owner": LOCAL_USER_ID, "id": goal_id},
        ).fetchone()
        if row is None:
            raise GoalNotFoundError(goal_id)
        return Goal(
            **self._summary(row),
            desired_outcome=row["desired_outcome"],
            duration=row["duration"],
            assessment_type=row["assessment_type"],
            success_criteria=row["success_criteria"],
            measurement_plan=row["measurement_plan"],
        )

    @staticmethod
    def _summary(row: sqlite3.Row) -> GoalSummary:
        return GoalSummary(
            id=row["id"],
            status=row["status"],
            title=row["title"],
            revision=row["revision"],
            operator=row["operator"],
        )

    @staticmethod
    def _add_revision(
        connection: sqlite3.Connection,
        goal_id: int,
        revision: int,
        title: str,
        definition: GoalDefinition,
    ) -> None:
        connection.execute(
            """
            INSERT INTO goal_revisions (
                goal_id, revision, title, desired_outcome, duration,
                assessment_type, success_criteria, measurement_plan
            )
            VALUES (
                :goal_id, :revision, :title, :desired_outcome, :duration,
                :assessment_type, :success_criteria, :measurement_plan
            )
            """,
            {"goal_id": goal_id, "revision": revision, "title": title, **definition},
        )

    @staticmethod
    def _record_message(
        connection: sqlite3.Connection, goal_id: int, actor: str, text: str
    ) -> None:
        connection.execute(
            """
            INSERT INTO goal_events (goal_id, revision, kind, actor, payload)
            VALUES (?, 1, 'message', ?, ?)
            """,
            (goal_id, actor, json.dumps({"text": text}, ensure_ascii=False)),
        )
