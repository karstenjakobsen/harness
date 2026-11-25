import json
import sqlite3
from collections.abc import Generator
from contextlib import closing, contextmanager
from importlib.resources import files
from pathlib import Path
from types import EllipsisType
from typing import Literal, TypedDict, get_args

DATABASE_PATH = Path(".harness/goals.sqlite3")
LOCAL_USER_ID = "local"
MIGRATIONS = (
    "001_initial.sql",
    "002_goal_deletion.sql",
    "003_goal_definition.sql",
    "004_goal_tree.sql",
)

EVENT_COLUMNS = """
event.id AS event_id, event.actor, event.recorded_at, event.payload
"""
COMPLETION_JOIN = """
LEFT JOIN goal_events AS event
    ON event.goal_id = revision.goal_id AND event.revision = revision.revision
    AND event.kind = 'completion'
"""

SELECT_GOALS = f"""
SELECT goal.id, goal.status, goal.parent_goal_id, revision.title, revision.revision,
       revision.desired_outcome, revision.duration, revision.assessment_type,
       revision.duration_days, revision.success_criteria, revision.measurement_plan,
       operator.name AS operator, {EVENT_COLUMNS}
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
{COMPLETION_JOIN}
WHERE goal.owner_user_id = :owner AND goal.deleted_at IS NULL
"""

type GoalStatus = Literal["draft", "active", "paused", "completed", "revoked"]
type GoalCreationStatus = Literal["draft", "active"]
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
    duration_days: int | None
    assessment_type: AssessmentType | None
    success_criteria: str | None
    measurement_plan: str | None


class Completion(TypedDict):
    event_id: int
    goal_id: int
    revision: int
    recorded_by: str
    recorded_at: str
    evidence_kind: Literal["owner_confirmation", "owner_supplied_reference"]
    evidence: str


class Goal(GoalSummary, GoalDefinition):
    parent_goal_id: int | None
    completion: Completion | None


class GoalTree(TypedDict):
    root_id: int
    goals: list[Goal]


class GoalRevision(GoalDefinition):
    revision: int
    title: str
    completion: Completion | None


class GoalNotFoundError(LookupError):
    def __init__(self, goal_id: int) -> None:
        super().__init__(f"Goal {goal_id} was not found.")


class GoalValidationError(ValueError):
    """The requested goal definition is invalid."""


class GoalConflictError(RuntimeError):
    """The current state of a goal prevents the requested operation."""


class GoalStorageError(RuntimeError):
    """The goal database could not be accessed."""

    def __init__(self) -> None:
        super().__init__("The goals database is unavailable.")


def _normalize_title(title: str) -> str:
    title = title.strip()
    if not title:
        raise GoalValidationError("A goal title is required.")
    return title


def _validate_integer(value: int, label: str, minimum: int = -(2**63)) -> None:
    if type(value) is not int or not minimum <= value < 2**63:
        raise GoalValidationError(
            f"{label} must be an integer between {minimum} and {2**63 - 1}."
        )


def _validate_definition(definition: GoalDefinition) -> None:
    if definition["duration_days"] is not None:
        _validate_integer(definition["duration_days"], "Duration in days", minimum=1)
    if definition["duration"] is not None and definition["duration"] not in get_args(
        GoalDuration.__value__
    ):
        raise GoalValidationError("Duration must be one_time or standing.")
    if definition["assessment_type"] is not None and definition[
        "assessment_type"
    ] not in get_args(AssessmentType.__value__):
        raise GoalValidationError(
            "Assessment type must be objective, judgment, or mixed."
        )


def _revised[T](current: T, change: T | EllipsisType) -> T:
    """Omitting a field preserves it. An explicit None clears it."""
    return current if change is ... else change


def _completion(row: sqlite3.Row) -> Completion | None:
    if row["event_id"] is None:
        return None
    return Completion(
        event_id=row["event_id"],
        goal_id=row["id"],
        revision=row["revision"],
        recorded_by=row["actor"],
        recorded_at=row["recorded_at"],
        **json.loads(row["payload"]),
    )


def _definition(row: sqlite3.Row | Goal) -> GoalDefinition:
    return GoalDefinition(
        desired_outcome=row["desired_outcome"],
        duration=row["duration"],
        duration_days=row["duration_days"],
        assessment_type=row["assessment_type"],
        success_criteria=row["success_criteria"],
        measurement_plan=row["measurement_plan"],
    )


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
        parent_goal_id: int | None = None,
        status: GoalCreationStatus = "draft",
        desired_outcome: str | None = None,
        duration: GoalDuration | None = None,
        duration_days: int | None = None,
        assessment_type: AssessmentType | None = None,
        success_criteria: str | None = None,
        measurement_plan: str | None = None,
        original_message: str | None = None,
        clarification: str | None = None,
    ) -> Goal:
        """Create a goal and its first definition in one transaction."""
        title = _normalize_title(title)
        if status not in get_args(GoalCreationStatus.__value__):
            raise GoalValidationError("A new goal must be draft or active.")
        definition = GoalDefinition(
            desired_outcome=desired_outcome,
            duration=duration,
            duration_days=duration_days,
            assessment_type=assessment_type,
            success_criteria=success_criteria,
            measurement_plan=measurement_plan,
        )
        _validate_definition(definition)
        with self._write() as connection:
            if parent_goal_id is not None:
                self._get_goal(connection, parent_goal_id)
            goal_id = connection.execute(
                "INSERT INTO goals (owner_user_id, parent_goal_id, status) VALUES (?, ?, ?) RETURNING id",
                (LOCAL_USER_ID, parent_goal_id, status),
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

    def get_goal_tree(self, goal_id: int) -> GoalTree:
        """Return the visible subtree as goal records linked by parent ID."""
        _validate_integer(goal_id, "Goal ID")
        with self._connection(read_only=True) as connection:
            rows = connection.execute(
                """
                WITH RECURSIVE subtree(id) AS (
                    SELECT id FROM goals
                    WHERE id = :id AND owner_user_id = :owner AND deleted_at IS NULL
                    UNION
                    SELECT child.id FROM goals AS child
                    JOIN subtree ON child.parent_goal_id = subtree.id
                    WHERE child.owner_user_id = :owner AND child.deleted_at IS NULL
                )
                """
                + SELECT_GOALS
                + " AND goal.id IN subtree ORDER BY goal.id",
                {"id": goal_id, "owner": LOCAL_USER_ID},
            )
            goals = [self._goal(row) for row in rows]
        if not goals:
            raise GoalNotFoundError(goal_id)
        return GoalTree(root_id=goal_id, goals=goals)

    def get_goal_history(self, goal_id: int) -> list[GoalRevision]:
        with self._connection(read_only=True) as connection:
            connection.execute("BEGIN")
            self._get_goal(connection, goal_id)
            rows = connection.execute(
                f"""
                SELECT revision.*, revision.goal_id AS id, {EVENT_COLUMNS}
                FROM goal_revisions AS revision {COMPLETION_JOIN}
                WHERE revision.goal_id = ? ORDER BY revision.revision
                """,
                (goal_id,),
            )
            return [
                GoalRevision(
                    **_definition(row),
                    revision=row["revision"],
                    title=row["title"],
                    completion=_completion(row),
                )
                for row in rows
            ]

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
        duration: GoalDuration | None | EllipsisType = ...,
        duration_days: int | None | EllipsisType = ...,
        assessment_type: AssessmentType | None | EllipsisType = ...,
        success_criteria: str | None | EllipsisType = ...,
        measurement_plan: str | None | EllipsisType = ...,
    ) -> Goal:
        """Append a revision for a changed definition. Omit fields to keep their values."""
        with self._write() as connection:
            goal = self._get_goal(connection, goal_id)
            title = goal["title"] if title is None else _normalize_title(title)
            definition = GoalDefinition(
                desired_outcome=_revised(goal["desired_outcome"], desired_outcome),
                duration=_revised(goal["duration"], duration),
                duration_days=_revised(goal["duration_days"], duration_days),
                assessment_type=_revised(goal["assessment_type"], assessment_type),
                success_criteria=_revised(goal["success_criteria"], success_criteria),
                measurement_plan=_revised(goal["measurement_plan"], measurement_plan),
            )
            _validate_definition(definition)
            if title == goal["title"] and definition == _definition(goal):
                return goal
            if title is None:
                raise GoalValidationError("Add a title when updating an untitled goal.")
            self._add_revision(
                connection, goal_id, (goal["revision"] or 0) + 1, title, definition
            )
            if goal["status"] == "completed":
                connection.execute(
                    "UPDATE goals SET status = 'active' WHERE id = ?", (goal_id,)
                )
            return self._get_goal(connection, goal_id)

    def complete_goal(
        self,
        goal_id: int,
        revision: int,
        *,
        confirmation: str | None = None,
        reference: str | None = None,
    ) -> Completion:
        _validate_integer(revision, "Revision", minimum=1)
        with self._write() as connection:
            goal = self._get_goal(connection, goal_id)
            if revision != goal["revision"]:
                raise GoalValidationError(
                    f"Stale revision. Current revision is {goal['revision']}."
                )
            if (confirmation is None) == (reference is None):
                raise GoalValidationError(
                    "Supply exactly one confirmation or reference."
                )
            evidence = (confirmation or reference or "").strip()
            if not evidence:
                raise GoalValidationError("Completion evidence must contain text.")
            kind = (
                "owner_confirmation"
                if confirmation is not None
                else "owner_supplied_reference"
            )
            if goal["status"] == "completed":
                saved = goal["completion"]
                if (
                    saved
                    and saved["recorded_by"] == LOCAL_USER_ID
                    and saved["evidence_kind"] == kind
                    and saved["evidence"] == evidence
                ):
                    return saved
                raise GoalValidationError(
                    "This revision already has a different completion decision."
                )
            if goal["status"] == "revoked":
                raise GoalValidationError("A revoked goal cannot be completed.")
            connection.execute(
                """INSERT INTO goal_events (goal_id, revision, kind, actor, payload)
                   VALUES (?, ?, 'completion', ?, ?)""",
                (
                    goal_id,
                    revision,
                    LOCAL_USER_ID,
                    json.dumps({"evidence_kind": kind, "evidence": evidence}),
                ),
            )
            connection.execute(
                "UPDATE goals SET status = 'completed' WHERE id = ?", (goal_id,)
            )
            decision = self._get_goal(connection, goal_id)["completion"]
            assert decision is not None
            return decision

    def delete_goal(self, goal_id: int) -> None:
        """Hide a visible leaf and close its assignment in the same transaction."""
        with self._write() as connection:
            self._get_goal(connection, goal_id)
            child = connection.execute(
                """
                SELECT 1 FROM goals
                WHERE parent_goal_id = ? AND owner_user_id = ? AND deleted_at IS NULL
                LIMIT 1
                """,
                (goal_id, LOCAL_USER_ID),
            ).fetchone()
            if child is not None:
                raise GoalConflictError(
                    f"Goal {goal_id} has visible children. Delete its children first."
                )
            connection.execute(
                "UPDATE goals SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
                (goal_id,),
            )
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
        _validate_integer(goal_id, "Goal ID")
        row = connection.execute(
            SELECT_GOALS + " AND goal.id = :id",
            {"owner": LOCAL_USER_ID, "id": goal_id},
        ).fetchone()
        if row is None:
            raise GoalNotFoundError(goal_id)
        return self._goal(row)

    def _goal(self, row: sqlite3.Row) -> Goal:
        return Goal(
            **self._summary(row),
            **_definition(row),
            parent_goal_id=row["parent_goal_id"],
            completion=_completion(row),
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
                goal_id, revision, title, desired_outcome, duration, duration_days,
                assessment_type, success_criteria, measurement_plan
            )
            VALUES (
                :goal_id, :revision, :title, :desired_outcome, :duration, :duration_days,
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
