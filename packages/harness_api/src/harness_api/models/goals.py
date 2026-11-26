import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from functools import cached_property
from hashlib import sha256
from pathlib import Path
from types import EllipsisType
from typing import Literal, TypedDict, Unpack, cast, get_args, overload

from ..database import (
    ADMIN_USER_ID,
    DATABASE_PATH,
    WorkspaceDatabase,
    WorkspaceStorageError,
    schema_version,
    utc_timestamp,
)
from . import GoalStatus
from .activity import (
    ActivityReadEntry,
    ActivityReadReference,
    CallActivity,
    CallReference,
    DecisionReadReference,
    DefinitionAction,
    DefinitionGrant,
    GoalResultReference,
    HarnessTool,
    HistoryReadReference,
    ObservationReadReference,
    OperatorRun,
    RevisionReadReference,
    RevisionReference,
    SkillReference,
    related_calls,
    revision_reference,
    run_calls,
    run_read_reference,
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
from .skills import SkillAPI, is_skill_id

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


class GoalDefinitionChanges(TypedDict, total=False):
    desired_outcome: str | None
    duration: GoalDuration | None
    duration_days: int | None
    assessment_type: AssessmentType | None
    success_criteria: str | None
    measurement_plan: str | None
    target_distinct_dates: int | None
    window_start: str | None


class DelegatedGoalResult(RevisionReference):
    status: GoalStatus


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
    committing_call: CallReference | None


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


def _activity_read_reference(activity: GoalActivity) -> ActivityReadReference:
    timeline: list[ActivityReadEntry] = []
    for entry in activity["timeline"]:
        if entry["kind"] == "revision":
            timeline.append(
                RevisionReadReference(
                    kind="revision",
                    revision=entry["definition"]["revision"],
                    committing_call=entry["committing_call"],
                )
            )
        elif entry["kind"] == "observation":
            timeline.append(
                ObservationReadReference(
                    kind="observation", evidence_id=entry["observation"]["evidence_id"]
                )
            )
        elif entry["kind"] == "decision":
            decision = entry["decision"]
            timeline.append(
                DecisionReadReference(
                    kind="decision",
                    event_id=decision["event_id"],
                    evidence_ids=decision["evidence_ids"],
                    statement_evidence_id=decision.get("statement_evidence_id"),
                    committing_call=entry["committing_call"],
                )
            )
        else:
            timeline.append(entry)
    return ActivityReadReference(goal_id=activity["goal_id"], timeline=timeline)


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


def _require_subgoal_schema(connection: sqlite3.Connection) -> None:
    if schema_version(connection) < 14:
        raise GoalValidationError(
            "Delegated subgoal creation requires a fresh workspace with schema version 14."
        )


def _merge_definition(
    definition: GoalDefinition, changes: GoalDefinitionChanges
) -> GoalDefinition:
    unknown = changes.keys() - definition.keys()
    if unknown:
        raise GoalValidationError(
            f"Unexpected definition fields: {', '.join(sorted(unknown))}"
        )
    merged: GoalDefinition = {**definition, **changes}
    _validate_definition(merged)
    return merged


def _new_definition(
    status: GoalCreationStatus, changes: GoalDefinitionChanges
) -> GoalDefinition:
    if status not in get_args(GoalCreationStatus.__value__):
        raise GoalValidationError("A new goal must be draft or active.")
    return _merge_definition(
        GoalDefinition(
            desired_outcome=None,
            duration=None,
            duration_days=None,
            assessment_type=None,
            success_criteria=None,
            measurement_plan=None,
            target_distinct_dates=None,
            window_start=None,
        ),
        changes,
    )


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

    @cached_property
    def skills(self) -> SkillAPI:
        """The skill catalog in the same workspace as these runs."""
        return SkillAPI(self._path)

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
        definition = _new_definition(
            status,
            GoalDefinitionChanges(
                desired_outcome=desired_outcome,
                duration=duration,
                duration_days=duration_days,
                assessment_type=assessment_type,
                success_criteria=success_criteria,
                measurement_plan=measurement_plan,
                target_distinct_dates=target_distinct_dates,
                window_start=window_start,
            ),
        )
        with self._write() as connection:
            if parent_goal_id is not None:
                self._get_goal(connection, parent_goal_id)
            goal_id = self._insert_goal(
                connection, title, status, definition, parent_goal_id
            )
            if original_message is not None:
                self._record_message(connection, goal_id, "user", original_message)
            if clarification is not None:
                self._record_message(connection, goal_id, "operator", clarification)
            return self._get_goal(connection, goal_id)

    def _insert_goal(
        self,
        connection: sqlite3.Connection,
        title: str,
        status: GoalCreationStatus,
        definition: GoalDefinition,
        parent_goal_id: int | None = None,
    ) -> int:
        (goal_id,) = connection.execute(
            "INSERT INTO goals (owner_user_id, parent_goal_id, status) VALUES (?, ?, ?) RETURNING id",
            (ADMIN_USER_ID, parent_goal_id, status),
        ).fetchone()
        self._add_revision(connection, goal_id, 1, title, definition)
        return goal_id

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

    def get_goal_activity(
        self, goal_id: int, *, call: CallReference | None = None
    ) -> GoalActivity:
        """Read the owner-visible timeline in a consistent workspace snapshot."""
        with self._connection("ro") as connection:
            connection.execute("BEGIN")
            self._get_goal(connection, goal_id)
            self._validate_history_call(connection, call, "get_goal_activity", goal_id)
            history = self._goal_history(connection, goal_id)
            calls, decision_commits, revision_commits = related_calls(
                connection, goal_id, ADMIN_USER_ID, call
            )
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
                    kind="revision",
                    at=definition["created_at"],
                    definition=definition,
                    committing_call=revision_commits.get(definition["revision"]),
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
                        committing_call=decision_commits.get(decision["event_id"]),
                    )
                )
        return GoalActivity(
            goal_id=goal_id, timeline=sorted(timeline, key=_activity_order)
        )

    def start_run(
        self,
        completion_grant_id: int | None = None,
        *,
        definition_grant_id: int | None = None,
    ) -> OperatorRun:
        """Bind a run to the exact grant checked at launch, or start an advisory run."""
        if completion_grant_id is not None and definition_grant_id is not None:
            raise GoalValidationError("A run can bind only one grant.")
        with self._write() as connection:
            if completion_grant_id is not None:
                self._get_completion_grant(connection, completion_grant_id)
            if definition_grant_id is not None:
                self._get_definition_grant(connection, definition_grant_id)
            run_id = connection.execute(
                """
                INSERT INTO operator_runs (owner_user_id, completion_grant_id, definition_grant_id, started_at)
                VALUES (?, ?, ?, ?) RETURNING id
                """,
                (
                    ADMIN_USER_ID,
                    completion_grant_id,
                    definition_grant_id,
                    utc_timestamp(),
                ),
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

    def get_run_write_action(
        self, run_id: int
    ) -> DefinitionAction | Literal["complete_goal"] | None:
        """Return the action the run's exact grant currently authorizes."""
        _validate_positive_integer(run_id, "Run ID")
        with self._connection("ro") as connection:
            connection.execute("BEGIN")
            run = run_row(connection, run_id, ADMIN_USER_ID)
            if run["outcome"] != "unfinished":
                return None
            try:
                if run["definition_grant_id"] is not None:
                    return self._get_definition_grant(
                        connection, run["definition_grant_id"]
                    )["action"]
                if run["completion_grant_id"] is not None:
                    self._get_completion_grant(connection, run["completion_grant_id"])
                    return "complete_goal"
            except GoalValidationError:
                # Historical runs retain the grant ID after its authority ends.
                return None
            return None

    def get_run(self, run_id: int, *, call: CallReference | None = None) -> OperatorRun:
        _validate_positive_integer(run_id, "Run ID")
        exclude_sequence = (
            call["sequence"] if call is not None and call["run_id"] == run_id else None
        )
        with self._connection("ro") as connection:
            connection.execute("BEGIN")
            row = run_row(connection, run_id, ADMIN_USER_ID)
            self._validate_history_call(connection, call, "get_run", run_id)
            return run_record(row, run_calls(connection, run_id, exclude_sequence))

    def _validate_history_call(
        self,
        connection: sqlite3.Connection,
        call: CallReference | None,
        tool: Literal["get_goal_activity", "get_run"],
        target_id: int,
    ) -> None:
        if call is None:
            return
        attempt = self._open_tool_call(connection, call)
        target_field = "target_run_id" if tool == "get_run" else "target_goal_id"
        if attempt["tool"] != tool or attempt[target_field] != target_id:
            raise GoalValidationError(
                "The history call does not match the requested target."
            )

    def start_tool_call(
        self,
        run_id: int,
        tool: HarnessTool,
        *,
        target_goal_id: int | None = None,
        target_revision: int | None = None,
        target_run_id: int | None = None,
        target_skill_id: str | None = None,
    ) -> CallReference:
        _validate_positive_integer(run_id, "Run ID")
        if tool not in get_args(HarnessTool.__value__):
            raise GoalValidationError("Unknown Harness tool.")
        if target_goal_id is not None:
            if tool in ("list_skills", "read_skill"):
                raise GoalValidationError("Skill calls cannot have a goal target.")
            _validate_positive_integer(target_goal_id, "Target goal ID")
        if target_revision is not None:
            if tool == "list_skills":
                raise GoalValidationError("Catalog discovery cannot target a revision.")
            _validate_positive_integer(target_revision, "Target revision")
        if target_skill_id is not None and (
            tool != "read_skill" or not isinstance(target_skill_id, str)
        ):
            raise GoalValidationError("Only read_skill can request a skill ID.")
        if target_run_id is not None:
            _validate_positive_integer(target_run_id, "Target run ID")
            if tool != "get_run":
                raise GoalValidationError("Only get_run can request a run ID.")
        with self._write() as connection:
            run = run_row(connection, run_id, ADMIN_USER_ID)
            if run["outcome"] != "unfinished":
                raise GoalConflictError(f"Run {run_id} already finished.")
            if tool == "create_subgoal":
                _require_subgoal_schema(connection)
            sequence = connection.execute(
                "SELECT coalesce(max(sequence), 0) + 1 FROM run_calls WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO run_calls (
                    run_id, sequence, tool, target_goal_id, target_revision, target_run_id, target_skill_id,
                    started_at, resolved_goal_id
                ) VALUES (
                    :run_id, :sequence, :tool, :target_goal_id, :target_revision, :target_run_id, :target_skill_id,
                    :started_at,
                    (SELECT id FROM goals WHERE id = :target_goal_id
                        AND owner_user_id = :owner AND deleted_at IS NULL)
                )
                """,
                {
                    "run_id": run_id,
                    "sequence": sequence,
                    "tool": tool,
                    "target_goal_id": target_goal_id,
                    "target_revision": target_revision,
                    "target_run_id": target_run_id,
                    "target_skill_id": target_skill_id
                    if is_skill_id(target_skill_id)
                    else None,
                    "started_at": utc_timestamp(),
                    "owner": run["owner_user_id"],
                },
            )
        return CallReference(run_id=run_id, sequence=sequence)

    def finish_tool_call(
        self,
        call: CallReference,
        outcome: Literal["returned", "denied", "failed"],
        *,
        returned_goals: list[GoalResultReference] | None = None,
        history_result: GoalActivity | OperatorRun | None = None,
        returned_skills: list[SkillReference] | None = None,
    ) -> None:
        result_count = sum(
            value is not None
            for value in (returned_goals, history_result, returned_skills)
        )
        if outcome not in ("returned", "denied", "failed") or result_count != int(
            outcome == "returned"
        ):
            raise GoalValidationError("A returned call requires result references.")
        with self._write() as connection:
            attempt = self._open_tool_call(connection, call)
            if outcome == "denied" and any(
                attempt[field] is not None
                for field in (
                    "revision_kind",
                    "committed_event_id",
                    "retrieved_event_id",
                )
            ):
                raise GoalValidationError(
                    "A call with a saved result cannot be recorded as denied."
                )
            history_reference = None
            if returned_skills is not None:
                self._save_skill_references(connection, attempt, returned_skills)
            elif history_result is not None:
                history_reference = self._history_read_reference(
                    connection, attempt, history_result
                )
            elif returned_goals is not None:
                self._validate_tool_result(connection, attempt, returned_goals)
                save_result_references(connection, call, returned_goals)
            connection.execute(
                """
                UPDATE run_calls SET outcome = :outcome, finished_at = :finished_at,
                    returned_history = :returned_history
                WHERE run_id = :run_id AND sequence = :sequence
                """,
                dict(
                    call,
                    outcome=outcome,
                    finished_at=utc_timestamp(),
                    returned_history=json.dumps(
                        history_reference, separators=(",", ":")
                    )
                    if history_reference is not None
                    else None,
                ),
            )

    @staticmethod
    def _save_skill_references(
        connection: sqlite3.Connection,
        attempt: sqlite3.Row,
        skills: list[SkillReference],
    ) -> None:
        if attempt["tool"] not in ("list_skills", "read_skill"):
            raise GoalValidationError("The result type must match the tool call.")
        if attempt["tool"] == "read_skill" and skills != [
            {
                "id": attempt["target_skill_id"],
                "revision": attempt["target_revision"],
            }
        ]:
            raise GoalValidationError(
                "The returned skill must match the requested ID and revision."
            )
        listed_ids = set()
        for position, skill in enumerate(skills):
            if (
                not isinstance(skill, dict)
                or skill.keys() != {"id", "revision"}
                or not is_skill_id(skill["id"])
            ):
                raise GoalValidationError(
                    "A skill reference requires an ID and revision."
                )
            _validate_positive_integer(skill["revision"], "Skill revision")
            if skill["id"] in listed_ids:
                raise GoalValidationError(
                    "A skill can appear only once in a catalog listing."
                )
            listed_ids.add(skill["id"])
            cursor = connection.execute(
                """INSERT INTO run_call_skills (run_id, sequence, position, snapshot_id)
                   SELECT ?, ?, ?, id FROM skill_revisions
                   WHERE owner_user_id = ? AND skill_key = ? AND revision = ?""",
                (
                    attempt["run_id"],
                    attempt["sequence"],
                    position,
                    ADMIN_USER_ID,
                    skill["id"],
                    skill["revision"],
                ),
            )
            if cursor.rowcount != 1:
                raise GoalValidationError(
                    "The returned skill revision must exist in this workspace."
                )

    @staticmethod
    def _history_read_reference(
        connection: sqlite3.Connection,
        attempt: sqlite3.Row,
        history: GoalActivity | OperatorRun,
    ) -> HistoryReadReference:
        reference: HistoryReadReference
        calls: Iterable[CallReference]
        if (
            "goal_id" not in history
            and attempt["tool"] == "get_run"
            and attempt["target_run_id"] == history["id"]
        ):
            run_row(connection, history["id"], ADMIN_USER_ID)
            reference = run_read_reference(history)
            calls = reference["calls"]
        elif (
            "id" not in history
            and attempt["tool"] == "get_goal_activity"
            and attempt["target_goal_id"] == history["goal_id"]
            and connection.execute(
                "SELECT 1 FROM goals WHERE id = ? AND owner_user_id = ?",
                (history["goal_id"], ADMIN_USER_ID),
            ).fetchone()
        ):
            reference = _activity_read_reference(history)
            calls = (item for item in reference["timeline"] if item["kind"] == "call")
        else:
            raise GoalValidationError(
                "The history result must match the requested target."
            )
        if any(
            item["run_id"] == attempt["run_id"]
            and item["sequence"] == attempt["sequence"]
            for item in calls
        ):
            raise GoalValidationError("A history result cannot include its own call.")
        return reference

    @staticmethod
    def _validate_tool_result(
        connection: sqlite3.Connection,
        attempt: sqlite3.Row,
        goals: list[GoalResultReference],
    ) -> None:
        if attempt["tool"] in (
            "list_skills",
            "read_skill",
            "get_goal_activity",
            "get_run",
        ):
            raise GoalValidationError("The result type must match the tool call.")
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
        elif attempt["tool"] in ("create_goal", "create_subgoal", "revise_goal"):
            reference = revision_reference(attempt)
            if (
                reference is None
                or len(goals) != 1
                or goals[0]["goal_id"] != reference["goal_id"]
                or goals[0]["revision"] != reference["revision"]
                or goals[0]["status"] not in ("draft", "active", "paused")
                or (
                    attempt["tool"] == "create_subgoal"
                    and goals[0]["status"] != "draft"
                )
                or goals[0]["observation_ids"]
                or goals[0]["decision"] is not None
            ):
                raise GoalValidationError(
                    "The result must reference the call's goal revision."
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
            SELECT call.*, run.completion_grant_id, run.definition_grant_id,
                   run.outcome AS run_outcome, link.kind AS revision_kind,
                   link.goal_id AS revision_goal_id, link.revision AS saved_revision
            FROM run_calls AS call JOIN operator_runs AS run ON run.id = call.run_id
            LEFT JOIN run_call_revisions AS link
                ON link.run_id = call.run_id AND link.sequence = call.sequence
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
        changes = {
            "desired_outcome": desired_outcome,
            "duration": duration,
            "duration_days": duration_days,
            "assessment_type": assessment_type,
            "success_criteria": success_criteria,
            "measurement_plan": measurement_plan,
            "target_distinct_dates": target_distinct_dates,
            "window_start": window_start,
        }
        fields = cast(
            GoalDefinitionChanges,
            {field: value for field, value in changes.items() if value is not ...},
        )
        with self._write() as connection:
            goal = self._get_goal(connection, goal_id)
            if self._append_definition(connection, goal, title, fields) is None:
                return goal
            if goal["status"] == "completed":
                connection.execute(
                    "UPDATE goals SET status = 'active' WHERE id = ?", (goal_id,)
                )
            return self._get_goal(connection, goal_id)

    def _append_definition(
        self,
        connection: sqlite3.Connection,
        goal: Goal,
        title: str | None,
        fields: GoalDefinitionChanges,
    ) -> int | None:
        title = goal["title"] if title is None else _normalize_title(title)
        current = _definition(goal)
        definition = _merge_definition(current, fields)
        if title == goal["title"] and definition == current:
            return None
        if title is None:
            raise GoalValidationError("Add a title when updating an untitled goal.")
        revision = (goal["revision"] or 0) + 1
        self._add_revision(connection, goal["id"], revision, title, definition)
        return revision

    def grant_definition(
        self, action: DefinitionAction, operator_id: int, *, goal_id: int | None = None
    ) -> DefinitionGrant:
        """Grant a registered operator one definition action in its requested scope."""
        if self._submitter != ADMIN_USER_ID:
            raise GoalValidationError(
                "Only the workspace owner can delegate goal definitions."
            )
        _validate_positive_integer(operator_id, "Operator ID")
        if action not in get_args(DefinitionAction.__value__) or (
            action == "create_goal"
        ) != (goal_id is None):
            raise GoalValidationError(
                "Top-level creation takes no goal. Subgoal creation and revision require one goal."
            )
        with self._write() as connection:
            if action == "create_subgoal":
                _require_subgoal_schema(connection)
            if goal_id is not None:
                self._get_goal(connection, goal_id)
            operator = connection.execute(
                "SELECT id FROM operators WHERE id = ? AND owner_user_id = ? AND deleted_at IS NULL",
                (operator_id, ADMIN_USER_ID),
            ).fetchone()
            if operator is None:
                raise GoalValidationError(
                    "Choose a registered operator owned by the workspace owner."
                )
            (grant_id,) = connection.execute(
                """
                INSERT INTO goal_definition_grants (operator_id, goal_id, action, granted_at)
                VALUES (?, ?, ?, ?) RETURNING id
                """,
                (operator_id, goal_id, action, utc_timestamp()),
            ).fetchone()
            return DefinitionGrant(
                id=grant_id, operator_id=operator_id, action=action, goal_id=goal_id
            )

    def get_definition_grant(self, grant_id: int) -> DefinitionGrant:
        """Resolve an active definition grant at session startup."""
        with self._connection("ro") as connection:
            return self._get_definition_grant(connection, grant_id)

    def withdraw_definition_grant(self, grant_id: int) -> DefinitionGrant:
        """Withdraw definition authority without changing an assignment."""
        if self._submitter != ADMIN_USER_ID:
            raise GoalValidationError(
                "Only the workspace owner can withdraw a definition grant."
            )
        with self._write() as connection:
            grant = self._get_definition_grant(connection, grant_id)
            connection.execute(
                "UPDATE goal_definition_grants SET withdrawn_at = ? WHERE id = ?",
                (utc_timestamp(), grant_id),
            )
            return grant

    @staticmethod
    def _get_definition_grant(
        connection: sqlite3.Connection, grant_id: int
    ) -> DefinitionGrant:
        _validate_positive_integer(grant_id, "Definition grant ID")
        row = connection.execute(
            """
            SELECT grant.id, grant.operator_id, grant.action, grant.goal_id
            FROM goal_definition_grants AS grant
            JOIN operators AS operator ON operator.id = grant.operator_id
            LEFT JOIN goals AS goal ON goal.id = grant.goal_id
            WHERE grant.id = ? AND grant.withdrawn_at IS NULL
                AND operator.owner_user_id = ? AND operator.deleted_at IS NULL
                AND (grant.goal_id IS NULL OR (goal.owner_user_id = operator.owner_user_id AND goal.deleted_at IS NULL))
            """,
            (grant_id, ADMIN_USER_ID),
        ).fetchone()
        if row is None:
            raise GoalValidationError(
                f"Definition grant {grant_id} is inactive or unavailable."
            )
        return DefinitionGrant(
            id=row["id"],
            operator_id=row["operator_id"],
            action=row["action"],
            goal_id=row["goal_id"],
        )

    def _definition_write_grant(
        self,
        connection: sqlite3.Connection,
        call: CallReference,
        action: DefinitionAction,
        goal_id: int | None = None,
        expected_revision: int | None = None,
    ) -> DefinitionGrant:
        attempt = self._open_tool_call(connection, call)
        if (
            attempt["run_outcome"] != "unfinished"
            or attempt["tool"] != action
            or attempt["definition_grant_id"] is None
            or attempt["target_goal_id"] != goal_id
            or attempt["target_revision"] != expected_revision
        ):
            raise GoalValidationError(
                "The tool call does not match this delegated write."
            )
        grant = self._get_definition_grant(connection, attempt["definition_grant_id"])
        if grant["action"] != action or grant["goal_id"] != goal_id:
            raise GoalValidationError(
                "The definition grant does not cover this action and goal."
            )
        if attempt["revision_kind"] is not None:
            raise GoalConflictError(
                "This tool call already saved a revision result. Use a new call to retry."
            )
        return grant

    @staticmethod
    def _link_revision(
        connection: sqlite3.Connection,
        call: CallReference,
        reference: RevisionReference,
        kind: Literal["committed", "retrieved", "unchanged"],
    ) -> None:
        connection.execute(
            """
            INSERT INTO run_call_revisions (run_id, sequence, goal_id, revision, kind)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                call["run_id"],
                call["sequence"],
                reference["goal_id"],
                reference["revision"],
                kind,
            ),
        )

    def create_delegated_goal(
        self,
        title: str,
        *,
        call: CallReference,
        retry_key: str,
        status: GoalCreationStatus = "draft",
        **fields: Unpack[GoalDefinitionChanges],
    ) -> DelegatedGoalResult:
        """Save a top-level goal once for this grant and creation key."""
        return self._create_with_grant(title, call, retry_key, status, fields)

    def create_delegated_subgoal(
        self,
        parent_goal_id: int,
        expected_parent_revision: int,
        title: str,
        *,
        call: CallReference,
        retry_key: str,
        **fields: Unpack[GoalDefinitionChanges],
    ) -> DelegatedGoalResult:
        """Save a draft child against the parent revision reviewed by this call."""
        _validate_positive_integer(parent_goal_id, "Parent goal ID")
        _validate_positive_integer(expected_parent_revision, "Expected parent revision")
        criteria = fields.get("success_criteria")
        if not isinstance(criteria, str) or not criteria.strip():
            raise GoalValidationError("Subgoal success criteria must contain text.")
        return self._create_with_grant(
            title,
            call,
            retry_key,
            "draft",
            fields,
            parent_goal_id,
            expected_parent_revision,
        )

    def _create_with_grant(
        self,
        title: str,
        call: CallReference,
        retry_key: str,
        status: GoalCreationStatus,
        fields: GoalDefinitionChanges,
        parent_goal_id: int | None = None,
        expected_parent_revision: int | None = None,
    ) -> DelegatedGoalResult:
        title = _normalize_title(title)
        retry_key = _require_text(retry_key, "Retry key").strip()
        if not retry_key:
            raise GoalValidationError("Retry key must contain text.")
        definition = _new_definition(status, fields)
        request: list[object] = [title, status, definition]
        if parent_goal_id is not None:
            request.extend((parent_goal_id, expected_parent_revision))
        fingerprint = sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        with self._write() as connection:
            grant = self._definition_write_grant(
                connection,
                call,
                "create_goal" if parent_goal_id is None else "create_subgoal",
                parent_goal_id,
                expected_parent_revision,
            )
            parent = (
                self._get_goal(connection, parent_goal_id)
                if parent_goal_id is not None
                else None
            )
            if parent is not None and parent["revision"] != expected_parent_revision:
                raise GoalConflictError(
                    f"Stale parent revision. Current revision is {parent['revision']}."
                )
            existing = connection.execute(
                "SELECT goal_id, status, fingerprint FROM goal_creation_retries WHERE grant_id = ? AND retry_key = ?",
                (grant["id"], retry_key),
            ).fetchone()
            if existing is not None:
                if existing["fingerprint"] != fingerprint:
                    raise GoalConflictError(
                        "This retry key already identifies a different goal definition."
                    )
                self._get_goal(connection, existing["goal_id"])
                result = DelegatedGoalResult(
                    goal_id=existing["goal_id"], revision=1, status=existing["status"]
                )
                self._link_revision(connection, call, result, "retrieved")
                return result
            if parent is not None and parent["status"] not in (
                "draft",
                "active",
                "paused",
            ):
                raise GoalConflictError(
                    f"Cannot add a subgoal to a {parent['status']} parent."
                )
            goal_id = self._insert_goal(
                connection, title, status, definition, parent_goal_id
            )
            connection.execute(
                "INSERT INTO goal_creation_retries (grant_id, retry_key, fingerprint, goal_id, status) VALUES (?, ?, ?, ?, ?)",
                (grant["id"], retry_key, fingerprint, goal_id, status),
            )
            result = DelegatedGoalResult(goal_id=goal_id, revision=1, status=status)
            self._link_revision(connection, call, result, "committed")
            return result

    def revise_delegated_goal(
        self,
        goal_id: int,
        expected_revision: int,
        *,
        call: CallReference,
        title: str | None = None,
        **fields: Unpack[GoalDefinitionChanges],
    ) -> DelegatedGoalResult:
        """Revise the granted open goal if the reviewed revision is still current."""
        _validate_positive_integer(goal_id, "Goal ID")
        _validate_positive_integer(expected_revision, "Expected revision")
        with self._write() as connection:
            self._definition_write_grant(
                connection, call, "revise_goal", goal_id, expected_revision
            )
            goal = self._get_goal(connection, goal_id)
            if expected_revision != goal["revision"]:
                raise GoalConflictError(
                    f"Stale revision. Current revision is {goal['revision']}."
                )
            if goal["status"] not in ("draft", "active", "paused"):
                raise GoalConflictError(
                    f"The owner must revise a {goal['status']} goal."
                )
            revision = self._append_definition(connection, goal, title, fields)
            result = DelegatedGoalResult(
                goal_id=goal_id,
                revision=revision or expected_revision,
                status=goal["status"],
            )
            self._link_revision(
                connection,
                call,
                result,
                "unchanged" if revision is None else "committed",
            )
            return result

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
