import json
import sqlite3
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import EllipsisType
from typing import Literal, TypedDict, Unpack, get_args, overload

from ..database import (
    ADMIN_USER_ID,
    DATABASE_PATH,
    WorkspaceDatabase,
    WorkspaceStorageError,
    utc_timestamp,
)
from . import GoalStatus
from .activity import (
    CallActivity,
    CallReference,
    GoalResultReference,
    HarnessTool,
    OperatorRun,
    related_calls,
    run_calls,
    run_record,
    run_row,
    save_result_references,
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
event.completion_grant_id, grant.operator_id, json_extract(event.payload, '$.rationale') AS rationale,
(SELECT json_group_array(evidence_id) FROM completion_citations
 WHERE decision_id = event.id) AS evidence_ids
"""
COMPLETION_JOIN = """
LEFT JOIN goal_events AS event
    ON event.goal_id = revision.goal_id AND event.revision = revision.revision
    AND event.kind = 'completion'
LEFT JOIN goal_events AS statement ON statement.id = event.statement_evidence_id
LEFT JOIN goal_assignments AS grant ON grant.id = event.completion_grant_id
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


class _CompletionFields(TypedDict):
    event_id: int
    goal_id: int
    revision: int
    recorded_at: str
    evidence_ids: list[int]


class Completion(_CompletionFields):
    recorded_by: int | None
    statement_evidence_id: int
    evidence_kind: EvidenceSource
    evidence: str


class DelegatedCompletion(_CompletionFields):
    completion_grant_id: int
    recorded_by_operator_id: int
    rationale: str


class CompletionGrant(TypedDict):
    id: int
    goal_id: int
    operator_id: int


class Goal(GoalSummary, GoalDefinition):
    parent_goal_id: int | None
    completion: Completion | DelegatedCompletion | None


class GoalTree(TypedDict):
    root_id: int
    goals: list[Goal]


class RevisionDefinition(GoalDefinition):
    created_at: str
    revision: int
    title: str


class GoalRevision(RevisionDefinition):
    evidence: list[Evidence]
    completion: Completion | DelegatedCompletion | None


class RevisionActivity(TypedDict):
    kind: Literal["revision"]
    at: str
    definition: RevisionDefinition


class ObservationActivity(TypedDict):
    kind: Literal["observation"]
    at: str
    observation: Evidence


class DecisionActivity(TypedDict):
    kind: Literal["decision"]
    at: str
    decision: Completion | DelegatedCompletion
    committing_call: CallReference | None


type ActivityEntry = (
    RevisionActivity | ObservationActivity | DecisionActivity | CallActivity
)


class GoalActivity(TypedDict):
    goal_id: int
    timeline: list[ActivityEntry]


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


def _completion(row: sqlite3.Row) -> Completion | DelegatedCompletion | None:
    if row["event_id"] is None:
        return None
    fields = _CompletionFields(
        event_id=row["event_id"],
        goal_id=row["id"],
        revision=row["revision"],
        evidence_ids=sorted(json.loads(row["evidence_ids"])),
        recorded_at=row["recorded_at"],
    )
    if row["completion_grant_id"] is not None:
        return DelegatedCompletion(
            **fields,
            completion_grant_id=row["completion_grant_id"],
            recorded_by_operator_id=row["operator_id"],
            rationale=row["rationale"],
        )
    statement: EvidenceStatement = json.loads(row["payload"])
    return Completion(
        **fields,
        recorded_by=row["actor_user_id"],
        statement_evidence_id=row["statement_evidence_id"],
        evidence_kind=statement["evidence_kind"],
        evidence=statement["evidence"],
    )


def _definition(row: sqlite3.Row | GoalDefinition) -> GoalDefinition:
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


def _activity_order(entry: ActivityEntry) -> tuple[datetime, int, int, int]:
    timestamp = datetime.fromisoformat(entry["at"])
    timestamp = timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp
    match entry["kind"]:
        case "revision":
            return timestamp, 0, entry["definition"]["revision"], 0
        case "observation":
            return timestamp, 1, entry["observation"]["evidence_id"], 0
        case "call":
            return timestamp, 2, entry["run_id"], entry["sequence"]
        case "decision":
            return timestamp, 3, entry["decision"]["event_id"], 0


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
            return self._goal_history(connection, goal_id)

    @staticmethod
    def _goal_history(
        connection: sqlite3.Connection, goal_id: int
    ) -> list[GoalRevision]:
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

    def get_goal_activity(self, goal_id: int) -> GoalActivity:
        """Read the owner-visible timeline in a consistent workspace snapshot."""
        with self._connection("ro") as connection:
            connection.execute("BEGIN")
            self._get_goal(connection, goal_id)
            history = self._goal_history(connection, goal_id)
            calls, commits = related_calls(connection, goal_id, ADMIN_USER_ID)
        timeline: list[ActivityEntry] = list(calls)
        for revision in history:
            definition = RevisionDefinition(
                **_definition(revision),
                created_at=revision["created_at"],
                revision=revision["revision"],
                title=revision["title"],
            )
            timeline.append(
                RevisionActivity(
                    kind="revision", at=definition["created_at"], definition=definition
                )
            )
            for observation in revision["evidence"]:
                timeline.append(
                    ObservationActivity(
                        kind="observation",
                        at=observation["recorded_at"],
                        observation=observation,
                    )
                )
            if (decision := revision["completion"]) is not None:
                timeline.append(
                    DecisionActivity(
                        kind="decision",
                        at=decision["recorded_at"],
                        decision=decision,
                        committing_call=commits.get(decision["event_id"]),
                    )
                )
        return GoalActivity(
            goal_id=goal_id, timeline=sorted(timeline, key=_activity_order)
        )

    def start_run(self, completion_grant_id: int | None = None) -> OperatorRun:
        """Bind a run to the exact grant checked at launch, or start an advisory run."""
        with self._write() as connection:
            if completion_grant_id is not None:
                self._get_completion_grant(connection, completion_grant_id)
            run_id = connection.execute(
                """
                INSERT INTO operator_runs (owner_user_id, completion_grant_id, started_at)
                VALUES (?, ?, ?) RETURNING id
                """,
                (ADMIN_USER_ID, completion_grant_id, utc_timestamp()),
            ).fetchone()[0]
            return run_record(run_row(connection, run_id, ADMIN_USER_ID), [])

    def finish_run(self, run_id: int, outcome: Literal["succeeded", "failed"]) -> None:
        _validate_positive_integer(run_id, "Run ID")
        if outcome not in ("succeeded", "failed"):
            raise GoalValidationError("A finished run must succeed or fail.")
        with self._write() as connection:
            run = run_row(connection, run_id, ADMIN_USER_ID)
            if run["outcome"] == outcome:
                return
            if run["outcome"] != "unfinished":
                raise GoalConflictError(f"Run {run_id} already finished.")
            connection.execute(
                "UPDATE operator_runs SET outcome = ?, finished_at = ? WHERE id = ?",
                (outcome, utc_timestamp(), run_id),
            )

    def get_run(self, run_id: int) -> OperatorRun:
        _validate_positive_integer(run_id, "Run ID")
        with self._connection("ro") as connection:
            connection.execute("BEGIN")
            row = run_row(connection, run_id, ADMIN_USER_ID)
            return run_record(row, run_calls(connection, run_id))

    def start_tool_call(
        self,
        run_id: int,
        tool: HarnessTool,
        *,
        target_goal_id: int | None = None,
        target_revision: int | None = None,
    ) -> CallReference:
        _validate_positive_integer(run_id, "Run ID")
        if tool not in get_args(HarnessTool.__value__):
            raise GoalValidationError("Unknown Harness tool.")
        if target_goal_id is not None:
            _validate_positive_integer(target_goal_id, "Target goal ID")
        if target_revision is not None:
            _validate_positive_integer(target_revision, "Target revision")
        with self._write() as connection:
            run = run_row(connection, run_id, ADMIN_USER_ID)
            if run["outcome"] != "unfinished":
                raise GoalConflictError(f"Run {run_id} already finished.")
            sequence = connection.execute(
                "SELECT coalesce(max(sequence), 0) + 1 FROM run_calls WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO run_calls (run_id, sequence, tool, target_goal_id, target_revision, started_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    sequence,
                    tool,
                    target_goal_id,
                    target_revision,
                    utc_timestamp(),
                ),
            )
        return CallReference(run_id=run_id, sequence=sequence)

    def finish_tool_call(
        self,
        call: CallReference,
        outcome: Literal["returned", "denied", "failed"],
        *,
        returned_goals: list[GoalResultReference] | None = None,
    ) -> None:
        if outcome not in ("returned", "denied", "failed") or (
            outcome == "returned"
        ) != (returned_goals is not None):
            raise GoalValidationError("A returned call requires result references.")
        with self._write() as connection:
            attempt = self._open_tool_call(connection, call)
            if returned_goals is not None:
                self._validate_tool_result(connection, attempt, returned_goals)
                save_result_references(connection, call, returned_goals)
            connection.execute(
                """
                UPDATE run_calls SET outcome = :outcome, finished_at = :finished_at
                WHERE run_id = :run_id AND sequence = :sequence
                """,
                dict(call, outcome=outcome, finished_at=utc_timestamp()),
            )

    @staticmethod
    def _validate_tool_result(
        connection: sqlite3.Connection,
        attempt: sqlite3.Row,
        goals: list[GoalResultReference],
    ) -> None:
        if attempt["tool"] == "complete_goal":
            event_id = attempt["committed_event_id"] or attempt["retrieved_event_id"]
            if (
                event_id is None
                or len(goals) != 1
                or goals[0]["goal_id"] != attempt["target_goal_id"]
                or goals[0]["revision"] != attempt["target_revision"]
                or (decision := goals[0]["decision"]) is None
                or decision["event_id"] != event_id
            ):
                raise GoalValidationError(
                    "The completion result must reference the call's saved decision."
                )
        outside_scope = connection.execute(
            """
            SELECT 1 FROM json_each(?) AS result
            WHERE NOT EXISTS (
                SELECT 1 FROM goals WHERE id = result.value AND owner_user_id = ?
            ) LIMIT 1
            """,
            (json.dumps([goal["goal_id"] for goal in goals]), ADMIN_USER_ID),
        ).fetchone()
        if outside_scope is not None:
            raise GoalValidationError(
                "Every returned goal must belong to the workspace owner."
            )

    @staticmethod
    def _open_tool_call(
        connection: sqlite3.Connection, call: CallReference
    ) -> sqlite3.Row:
        _validate_positive_integer(call["run_id"], "Run ID")
        _validate_positive_integer(call["sequence"], "Call sequence")
        row = connection.execute(
            """
            SELECT call.*, run.completion_grant_id, run.outcome AS run_outcome
            FROM run_calls AS call JOIN operator_runs AS run ON run.id = call.run_id
            WHERE run.owner_user_id = :owner AND call.run_id = :run_id
                AND call.sequence = :sequence AND call.outcome = 'unfinished'
            """,
            dict(call, owner=ADMIN_USER_ID),
        ).fetchone()
        if row is None:
            raise GoalValidationError("The tool call is unavailable or finished.")
        return row

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

    def grant_completion(self, goal_id: int, operator_id: int) -> CompletionGrant:
        """Give a registered operator a new completion grant for one subgoal."""
        if self._submitter != ADMIN_USER_ID:
            raise GoalValidationError("Only the workspace owner can grant completion.")
        _validate_positive_integer(operator_id, "Operator ID")
        with self._write() as connection:
            goal = self._get_goal(connection, goal_id)
            if goal["parent_goal_id"] is None:
                raise GoalValidationError(
                    "Completion can only be granted for a subgoal."
                )
            operator = connection.execute(
                """
                SELECT id FROM operators
                WHERE id = ? AND owner_user_id = ? AND deleted_at IS NULL
                """,
                (operator_id, ADMIN_USER_ID),
            ).fetchone()
            if operator is None:
                raise GoalValidationError(
                    "Choose a registered operator owned by the workspace owner."
                )
            connection.execute(
                """
                UPDATE goal_assignments SET released_at = CURRENT_TIMESTAMP
                WHERE goal_id = ? AND released_at IS NULL
                """,
                (goal_id,),
            )
            (grant_id,) = connection.execute(
                """
                INSERT INTO goal_assignments (goal_id, operator_id, completion_granted_at)
                VALUES (?, ?, CURRENT_TIMESTAMP) RETURNING id
                """,
                (goal_id, operator_id),
            ).fetchone()
            return CompletionGrant(
                id=grant_id, goal_id=goal_id, operator_id=operator_id
            )

    def get_completion_grant(self, grant_id: int) -> CompletionGrant:
        """Resolve a completion grant at session startup."""
        with self._connection("ro") as connection:
            return self._get_completion_grant(connection, grant_id)

    def withdraw_completion(self, grant_id: int) -> CompletionGrant:
        """Close the granted assignment and invalidate sessions bound to it."""
        if self._submitter != ADMIN_USER_ID:
            raise GoalValidationError(
                "Only the workspace owner can withdraw completion."
            )
        with self._write() as connection:
            grant = self._get_completion_grant(connection, grant_id)
            connection.execute(
                "UPDATE goal_assignments SET released_at = CURRENT_TIMESTAMP WHERE id = ?",
                (grant_id,),
            )
            return grant

    @staticmethod
    def _get_completion_grant(
        connection: sqlite3.Connection, grant_id: int
    ) -> CompletionGrant:
        _validate_positive_integer(grant_id, "Completion grant ID")
        row = connection.execute(
            """
            SELECT assignment.id, assignment.goal_id, assignment.operator_id
            FROM goal_assignments AS assignment
            JOIN goals AS goal ON goal.id = assignment.goal_id AND goal.deleted_at IS NULL
            JOIN operators AS operator ON operator.id = assignment.operator_id
                AND operator.owner_user_id = goal.owner_user_id AND operator.deleted_at IS NULL
            WHERE assignment.id = ? AND assignment.released_at IS NULL
                AND assignment.completion_granted_at IS NOT NULL
                AND goal.owner_user_id = ? AND goal.parent_goal_id IS NOT NULL
            """,
            (grant_id, ADMIN_USER_ID),
        ).fetchone()
        if row is None:
            raise GoalValidationError(
                f"Completion grant {grant_id} is inactive or unavailable."
            )
        return CompletionGrant(
            id=row["id"], goal_id=row["goal_id"], operator_id=row["operator_id"]
        )

    @overload
    def complete_goal(
        self,
        goal_id: int,
        revision: int,
        *,
        confirmation: str | None = None,
        reference: str | None = None,
        evidence_ids: list[int] | tuple[int, ...] = (),
    ) -> Completion: ...

    @overload
    def complete_goal(
        self,
        goal_id: int,
        revision: int,
        *,
        completion_grant_id: int,
        rationale: str,
        evidence_ids: list[int] | tuple[int, ...],
        call: CallReference | None = None,
    ) -> DelegatedCompletion: ...

    def complete_goal(
        self,
        goal_id: int,
        revision: int,
        *,
        confirmation: str | None = None,
        reference: str | None = None,
        evidence_ids: list[int] | tuple[int, ...] = (),
        completion_grant_id: int | None = None,
        rationale: str | None = None,
        call: CallReference | None = None,
    ) -> Completion | DelegatedCompletion:
        _validate_positive_integer(revision, "Revision")
        with self._write() as connection:
            goal = self._get_goal(connection, goal_id)
            if completion_grant_id is not None:
                grant = self._get_completion_grant(connection, completion_grant_id)
                if grant["goal_id"] != goal_id:
                    raise GoalValidationError(
                        "This completion grant belongs to a different subgoal."
                    )
            if revision != goal["revision"]:
                raise GoalValidationError(
                    f"Stale revision. Current revision is {goal['revision']}."
                )
            if call is not None:
                attempt = self._open_tool_call(connection, call)
                if (
                    completion_grant_id is None
                    or attempt["completion_grant_id"] != completion_grant_id
                    or attempt["run_outcome"] != "unfinished"
                    or attempt["tool"] != "complete_goal"
                    or attempt["target_goal_id"] != goal_id
                    or attempt["target_revision"] != revision
                    or attempt["committed_event_id"] is not None
                    or attempt["retrieved_event_id"] is not None
                ):
                    raise GoalValidationError(
                        "The tool call does not match this completion."
                    )
            if completion_grant_id is None:
                if rationale is not None:
                    raise GoalValidationError(
                        "A rationale requires a completion grant."
                    )
                statement = self._statement(confirmation, reference)
                actor = self._submitter
                decision_fields: dict[str, object] = {"recorded_by": actor, **statement}
            else:
                rationale = _require_text(rationale, "Rationale").strip()
                if not rationale or confirmation is not None or reference is not None:
                    raise GoalValidationError(
                        "Delegated completion requires a rationale and existing evidence IDs."
                    )
                statement = None
                actor = None
                decision_fields = {
                    "completion_grant_id": completion_grant_id,
                    "rationale": rationale,
                }
            if not isinstance(evidence_ids, (list, tuple)):
                raise GoalValidationError(
                    "Evidence IDs must be a list or tuple of integers."
                )
            for evidence_id in evidence_ids:
                _validate_positive_integer(evidence_id, "Evidence ID")
            citations = sorted(set(evidence_ids))
            if statement is None and not citations:
                raise GoalValidationError(
                    "Delegated completion must cite at least one observation."
                )
            if goal["status"] == "completed":
                saved = goal["completion"]
                if (
                    saved
                    and saved["evidence_ids"] == citations
                    and all(
                        saved.get(key) == value
                        for key, value in decision_fields.items()
                    )
                ):
                    if call is not None:
                        connection.execute(
                            """
                            UPDATE run_calls SET retrieved_event_id = :event_id
                            WHERE run_id = :run_id AND sequence = :sequence
                            """,
                            dict(call, event_id=saved["event_id"]),
                        )
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
            statement_id = None
            if statement is not None:
                statement_id = add_evidence(
                    connection, goal_id, revision, actor, statement
                )["evidence_id"]
            timestamp = utc_timestamp()
            decision_id = connection.execute(
                """INSERT INTO goal_events (
                    goal_id, revision, kind, actor_user_id, payload, statement_evidence_id,
                    completion_grant_id, occurred_at, recorded_at
                ) VALUES (?, ?, 'completion', ?, ?, ?, ?, ?, ?) RETURNING id""",
                (
                    goal_id,
                    revision,
                    actor,
                    json.dumps({"rationale": rationale})
                    if rationale is not None
                    else "{}",
                    statement_id,
                    completion_grant_id,
                    timestamp,
                    timestamp,
                ),
            ).fetchone()[0]
            connection.executemany(
                "INSERT INTO completion_citations (goal_id, decision_id, evidence_id) VALUES (?, ?, ?)",
                [(goal_id, decision_id, evidence_id) for evidence_id in citations],
            )
            connection.execute(
                "UPDATE goals SET status = 'completed' WHERE id = ?", (goal_id,)
            )
            if call is not None:
                connection.execute(
                    """
                    UPDATE run_calls SET committed_event_id = :event_id
                    WHERE run_id = :run_id AND sequence = :sequence
                    """,
                    dict(call, event_id=decision_id),
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
                assessment_type, success_criteria, measurement_plan, target_distinct_dates, window_start,
                created_at
            )
            VALUES (
                :goal_id, :revision, :title, :desired_outcome, :duration, :duration_days,
                :assessment_type, :success_criteria, :measurement_plan, :target_distinct_dates, :window_start,
                :created_at
            )
            """,
            {
                "goal_id": goal_id,
                "revision": revision,
                "title": title,
                "created_at": utc_timestamp(),
                **definition,
            },
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
