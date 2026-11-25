import json
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from types import EllipsisType
from typing import Literal, TypedDict, Unpack, get_args

from ..database import (
    ADMIN_USER_ID,
    DATABASE_PATH,
    WorkspaceDatabase,
    WorkspaceStorageError,
)
from .evidence import (
    DateAssessment,
    Evidence,
    EvidenceSource,
    EvidenceStatement,
    add_evidence,
    assess_dates,
    evidence_record,
    goal_evidence,
    is_future_dated,
)

EVENT_COLUMNS = """
event.id AS event_id, event.actor_user_id, event.recorded_at, statement.payload, event.statement_evidence_id,
(SELECT json_group_array(evidence_id) FROM completion_citations
 WHERE decision_id = event.id) AS evidence_ids
"""
COMPLETION_JOIN = """
LEFT JOIN goal_events AS event
    ON event.goal_id = revision.goal_id AND event.revision = revision.revision
    AND event.kind = 'completion'
LEFT JOIN goal_events AS statement ON statement.id = event.statement_evidence_id
"""

SELECT_GOALS = f"""
SELECT goal.id, goal.status, goal.parent_goal_id, revision.title, revision.revision,
       revision.desired_outcome, revision.duration, revision.assessment_type,
       revision.duration_days, revision.target_distinct_dates, revision.window_start,
       revision.success_criteria, revision.measurement_plan,
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
    AND operator.deleted_at IS NULL
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


class _GoalFields(TypedDict):
    desired_outcome: str | None
    duration: GoalDuration | None
    duration_days: int | None
    assessment_type: AssessmentType | None
    success_criteria: str | None
    measurement_plan: str | None


class GoalDraftFields(_GoalFields, total=False):
    """Draft callers may omit the structured date criteria."""

    target_distinct_dates: int | None
    window_start: str | None


class GoalDefinition(_GoalFields):
    target_distinct_dates: int | None
    window_start: str | None


class GoalProgress(DateAssessment):
    goal_id: int
    revision: int | None
    status: GoalStatus


class Completion(TypedDict):
    event_id: int
    goal_id: int
    revision: int
    recorded_by: int | None
    recorded_at: str
    statement_evidence_id: int
    evidence_ids: list[int]
    evidence_kind: EvidenceSource
    evidence: str


class Goal(GoalSummary, GoalDefinition):
    parent_goal_id: int | None
    completion: Completion | None


class GoalTree(TypedDict):
    root_id: int
    goals: list[Goal]


class GoalRevision(GoalDefinition):
    created_at: str
    evidence: list[Evidence]
    revision: int
    title: str
    completion: Completion | None


class GoalNotFoundError(LookupError):
    def __init__(self, goal_id: int) -> None:
        super().__init__(f"Goal {goal_id} was not found.")


class GoalValidationError(ValueError):
    """A goal operation received invalid input."""


class GoalConflictError(RuntimeError):
    """The current state of a goal prevents the requested operation."""


class GoalStorageError(WorkspaceStorageError):
    """The goal database could not be accessed."""

    def __init__(self, message: str = "The goals database is unavailable.") -> None:
        super().__init__(message)


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise GoalValidationError(f"{field} must be text.")
    return value


def _normalize_title(title: str) -> str:
    title = _require_text(title, "Goal title").strip()
    if not title:
        raise GoalValidationError("A goal title is required.")
    return title


def _validate_positive_integer(value: int, label: str) -> None:
    if type(value) is not int or not 1 <= value < 2**63:
        raise GoalValidationError(f"{label} must be a positive 64-bit integer.")


def _calendar_date(value: str, label: str) -> str:
    try:
        if date.fromisoformat(value).isoformat() == value:
            return value
    except ValueError, TypeError:
        pass
    raise GoalValidationError(f"{label} must be a calendar date in YYYY-MM-DD format.")


def _validate_definition(definition: GoalDefinition) -> None:
    if definition["target_distinct_dates"] is not None:
        _validate_positive_integer(
            definition["target_distinct_dates"], "Target distinct dates"
        )
    if definition["window_start"] is not None:
        _calendar_date(definition["window_start"], "Window start")
        if definition["duration_days"] is None:
            raise GoalValidationError("A window start requires a duration in days.")

    for field in ("desired_outcome", "success_criteria", "measurement_plan"):
        value = definition[field]
        if value is not None:
            _require_text(value, field)
    if definition["duration_days"] is not None:
        _validate_positive_integer(definition["duration_days"], "Duration in days")
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


def _reported_date_window(
    connection: sqlite3.Connection, goal_id: int, definition: GoalDefinition
) -> tuple[str, str] | None:
    days = definition["duration_days"]
    if definition["target_distinct_dates"] is None or days is None:
        return None
    start = definition["window_start"]
    if start is None:
        (start,) = connection.execute(
            "SELECT date(created_at) FROM goals WHERE id = ?", (goal_id,)
        ).fetchone()
        if start is None:
            raise GoalValidationError(
                "Supply a window start for a goal without a valid creation date."
            )
    try:
        end = date.fromisoformat(start) + timedelta(days=days - 1)
    except OverflowError as error:
        raise GoalValidationError(
            "The date window exceeds the supported calendar."
        ) from error
    return start, end.isoformat()


def _completion(row: sqlite3.Row) -> Completion | None:
    if row["event_id"] is None:
        return None
    statement: EvidenceStatement = json.loads(row["payload"])
    return Completion(
        event_id=row["event_id"],
        goal_id=row["id"],
        revision=row["revision"],
        recorded_by=row["actor_user_id"],
        statement_evidence_id=row["statement_evidence_id"],
        evidence_ids=sorted(json.loads(row["evidence_ids"])),
        recorded_at=row["recorded_at"],
        evidence_kind=statement["evidence_kind"],
        evidence=statement["evidence"],
    )


def _definition(row: sqlite3.Row | Goal) -> GoalDefinition:
    return GoalDefinition(
        target_distinct_dates=row["target_distinct_dates"],
        window_start=row["window_start"],
        desired_outcome=row["desired_outcome"],
        duration=row["duration"],
        duration_days=row["duration_days"],
        assessment_type=row["assessment_type"],
        success_criteria=row["success_criteria"],
        measurement_plan=row["measurement_plan"],
    )


class GoalAPI(WorkspaceDatabase):
    """Admin-scoped workspace operations. Local calls run as the workspace owner.

    Entry points without an established owner use local_owner=False for attribution.
    """

    storage_error = GoalStorageError

    def __init__(
        self, path: Path | str = DATABASE_PATH, *, local_owner: bool = True
    ) -> None:
        if not isinstance(local_owner, bool):
            raise GoalValidationError("local_owner must be a boolean.")
        super().__init__(path)
        self._submitter = ADMIN_USER_ID if local_owner else None

    def save_goal_draft(
        self,
        original_message: str,
        *,
        title: str,
        clarification: str | None,
        **definition: Unpack[GoalDraftFields],
    ) -> tuple[Goal, str | None]:
        """Save the proposed definition and return the recorded clarification, if any."""
        if clarification is not None:
            clarification = _require_text(clarification, "Clarification").strip()
        question = clarification or None
        if question is None:
            if definition["duration"] is None:
                question = "Once I verify this, are we done, or do you want me to keep checking?"
            elif definition["assessment_type"] is None:
                question = "What would show that this goal is being met?"
        goal = self.create_goal(
            title,
            status="draft",
            original_message=_require_text(original_message, "Original message"),
            clarification=question,
            **definition,
        )
        return goal, question

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
        target_distinct_dates: int | None = None,
        window_start: str | None = None,
        original_message: str | None = None,
        clarification: str | None = None,
    ) -> Goal:
        """Create a goal and its first definition in one transaction."""
        title = _normalize_title(title)
        if status not in get_args(GoalCreationStatus.__value__):
            raise GoalValidationError("A new goal must be draft or active.")
        definition = GoalDefinition(
            target_distinct_dates=target_distinct_dates,
            window_start=window_start,
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
                (ADMIN_USER_ID, parent_goal_id, status),
            ).fetchone()[0]
            self._add_revision(connection, goal_id, 1, title, definition)
            if original_message is not None:
                self._record_message(connection, goal_id, "user", original_message)
            if clarification is not None:
                self._record_message(connection, goal_id, "operator", clarification)
            return self._get_goal(connection, goal_id)

    def get_goal(self, goal_id: int) -> Goal:
        with self._connection("ro") as connection:
            return self._get_goal(connection, goal_id)

    def get_goal_tree(self, goal_id: int) -> GoalTree:
        """Return the visible subtree as goal records linked by parent ID."""
        _validate_positive_integer(goal_id, "Goal ID")
        with self._connection("ro") as connection:
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
                {"id": goal_id, "owner": ADMIN_USER_ID},
            )
            goals = [self._goal(row) for row in rows]
        if not goals:
            raise GoalNotFoundError(goal_id)
        return GoalTree(root_id=goal_id, goals=goals)

    def get_goal_history(self, goal_id: int) -> list[GoalRevision]:
        with self._connection("ro") as connection:
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
            by_revision: dict[int, list[Evidence]] = defaultdict(list)
            for record in goal_evidence(connection, goal_id):
                by_revision[record["revision"]].append(record)
            return [
                GoalRevision(
                    created_at=row["created_at"],
                    evidence=by_revision[row["revision"]],
                    **_definition(row),
                    revision=row["revision"],
                    title=row["title"],
                    completion=_completion(row),
                )
                for row in rows
            ]

    def list_goals(self, status: GoalStatus | None = None) -> list[GoalSummary]:
        if status is not None and status not in get_args(GoalStatus.__value__):
            raise GoalValidationError(f"Unknown goal status {status!r}.")
        with self._connection("ro") as connection:
            rows = connection.execute(
                SELECT_GOALS
                + " AND (:status IS NULL OR goal.status = :status) ORDER BY goal.id",
                {"owner": ADMIN_USER_ID, "status": status},
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
        target_distinct_dates: int | None | EllipsisType = ...,
        window_start: str | None | EllipsisType = ...,
    ) -> Goal:
        """Append a revision for a changed definition. Omit fields to keep their values."""
        with self._write() as connection:
            goal = self._get_goal(connection, goal_id)
            title = goal["title"] if title is None else _normalize_title(title)
            definition = GoalDefinition(
                target_distinct_dates=_revised(
                    goal["target_distinct_dates"], target_distinct_dates
                ),
                window_start=_revised(goal["window_start"], window_start),
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

    def _statement(
        self, confirmation: str | None, reference: str | None
    ) -> EvidenceStatement:
        if (confirmation is None) == (reference is None):
            raise GoalValidationError("Supply exactly one confirmation or reference.")
        evidence = _require_text(
            confirmation if confirmation is not None else reference, "Evidence"
        ).strip()
        if not evidence:
            raise GoalValidationError("Evidence must contain text.")
        source: EvidenceSource
        if confirmation is not None:
            source = (
                "owner_confirmation" if self._submitter else "unattributed_confirmation"
            )
        else:
            source = (
                "owner_supplied_reference"
                if self._submitter
                else "unattributed_reference"
            )
        return {"evidence_kind": source, "evidence": evidence}

    def record_observation(
        self,
        goal_id: int,
        *,
        confirmation: str | None = None,
        reference: str | None = None,
        reported_date: str | None = None,
        retry_key: str,
    ) -> Evidence:
        """Save a report under the current revision, or return the original on retry."""
        payload = self._statement(confirmation, reference)
        payload["reported_date"] = (
            None
            if reported_date is None
            else _calendar_date(reported_date, "Reported date")
        )
        retry_key = _require_text(retry_key, "Retry key").strip()
        if not retry_key:
            raise GoalValidationError("Retry key must contain text.")
        with self._write() as connection:
            goal = self._get_goal(connection, goal_id)
            existing = connection.execute(
                """
                SELECT * FROM goal_events WHERE goal_id = ? AND kind = 'observation'
                    AND actor_user_id IS ? AND retry_key = ?
            """,
                (goal_id, self._submitter, retry_key),
            ).fetchone()
            if existing is not None:
                if json.loads(existing["payload"]) != payload:
                    raise GoalConflictError(
                        "This retry key already identifies a different observation."
                    )
                return evidence_record(existing)
            if goal["revision"] is None:
                raise GoalValidationError("A goal needs a revision to record evidence.")
            report = add_evidence(
                connection,
                goal_id,
                goal["revision"],
                self._submitter,
                payload,
                retry_key,
            )
            if is_future_dated(report):
                raise GoalValidationError(
                    "Reported date cannot be in the future (UTC)."
                )
            return report

    def get_goal_progress(
        self, goal_id: int, revision: int | None = None
    ) -> GoalProgress:
        """Evaluate the selected revision using all evidence available in this read transaction."""
        if revision is not None:
            _validate_positive_integer(revision, "Revision")
        with self._connection("ro") as connection:
            connection.execute("BEGIN")
            goal = self._get_goal(connection, goal_id)
            selected = goal["revision"] if revision is None else revision
            definition: GoalDefinition = goal
            if selected != goal["revision"]:
                row = connection.execute(
                    "SELECT * FROM goal_revisions WHERE goal_id = ? AND revision = ?",
                    (goal_id, selected),
                ).fetchone()
                if row is None:
                    raise GoalValidationError(
                        f"Goal {goal_id} has no revision {selected}."
                    )
                definition = _definition(row)
            assessment = assess_dates(
                goal_evidence(connection, goal_id),
                definition["target_distinct_dates"],
                _reported_date_window(connection, goal_id, definition),
            )
            return GoalProgress(
                goal_id=goal_id, revision=selected, status=goal["status"], **assessment
            )

    def complete_goal(
        self,
        goal_id: int,
        revision: int,
        *,
        confirmation: str | None = None,
        reference: str | None = None,
        evidence_ids: list[int] | tuple[int, ...] = (),
    ) -> Completion:
        _validate_positive_integer(revision, "Revision")
        with self._write() as connection:
            goal = self._get_goal(connection, goal_id)
            if revision != goal["revision"]:
                raise GoalValidationError(
                    f"Stale revision. Current revision is {goal['revision']}."
                )
            payload = self._statement(confirmation, reference)
            if not isinstance(evidence_ids, (list, tuple)):
                raise GoalValidationError(
                    "Evidence IDs must be a list or tuple of integers."
                )
            for evidence_id in evidence_ids:
                _validate_positive_integer(evidence_id, "Evidence ID")
            citations = sorted(set(evidence_ids))
            if goal["status"] == "completed":
                saved = goal["completion"]
                if (
                    saved
                    and saved["recorded_by"] == self._submitter
                    and saved["evidence_kind"] == payload["evidence_kind"]
                    and saved["evidence"] == payload["evidence"]
                    and saved["evidence_ids"] == citations
                ):
                    return saved
                raise GoalValidationError(
                    "This revision already has a different completion decision."
                )
            if goal["status"] == "revoked":
                raise GoalValidationError("A revoked goal cannot be completed.")
            if citations:
                valid = connection.execute(
                    """
                    SELECT count(*) FROM goal_events WHERE goal_id = ? AND kind = 'observation'
                    AND id IN (SELECT value FROM json_each(?))
                """,
                    (goal_id, json.dumps(citations)),
                ).fetchone()[0]
                if valid != len(citations):
                    raise GoalValidationError(
                        "Every cited evidence ID must belong to this goal."
                    )
            statement = add_evidence(
                connection, goal_id, revision, self._submitter, payload
            )
            decision_id = connection.execute(
                """INSERT INTO goal_events (goal_id, revision, kind, actor_user_id, payload, statement_evidence_id)
                   VALUES (?, ?, 'completion', ?, '{}', ?) RETURNING id""",
                (
                    goal_id,
                    revision,
                    self._submitter,
                    statement["evidence_id"],
                ),
            ).fetchone()[0]
            connection.executemany(
                "INSERT INTO completion_citations (goal_id, decision_id, evidence_id) VALUES (?, ?, ?)",
                [(goal_id, decision_id, evidence_id) for evidence_id in citations],
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
                (goal_id, ADMIN_USER_ID),
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

    def _get_goal(self, connection: sqlite3.Connection, goal_id: int) -> Goal:
        _validate_positive_integer(goal_id, "Goal ID")
        row = connection.execute(
            SELECT_GOALS + " AND goal.id = :id",
            {"owner": ADMIN_USER_ID, "id": goal_id},
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
        _reported_date_window(connection, goal_id, definition)
        connection.execute(
            """
            INSERT INTO goal_revisions (
                goal_id, revision, title, desired_outcome, duration, duration_days,
                assessment_type, success_criteria, measurement_plan, target_distinct_dates, window_start
            )
            VALUES (
                :goal_id, :revision, :title, :desired_outcome, :duration, :duration_days,
                :assessment_type, :success_criteria, :measurement_plan, :target_distinct_dates, :window_start
            )
            """,
            {"goal_id": goal_id, "revision": revision, "title": title, **definition},
        )

    @staticmethod
    def _record_message(
        connection: sqlite3.Connection, goal_id: int, role: str, text: str
    ) -> None:
        _require_text(text, "Goal message")
        connection.execute(
            """
            INSERT INTO goal_events (goal_id, revision, kind, message_role, payload)
            VALUES (?, 1, 'message', ?, ?)
            """,
            (goal_id, role, json.dumps({"text": text}, ensure_ascii=False)),
        )
