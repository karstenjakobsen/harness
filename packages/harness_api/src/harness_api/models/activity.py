"""Persist tool attempts and the references exposed in their results."""

import json
import sqlite3
from collections import defaultdict
from typing import Any, Literal, NotRequired, TypedDict

from . import GoalStatus

type HarnessTool = Literal[
    "list_goals",
    "get_goal_tree",
    "get_goal_progress",
    "get_goal_activity",
    "get_run",
    "list_skills",
    "read_skill",
    "delegate_work",
    "retry_work",
    "complete_goal",
    "create_goal",
    "create_subgoal",
    "revise_goal",
]
type DefinitionAction = Literal["create_goal", "create_subgoal", "revise_goal"]
type RunOutcome = Literal["unfinished", "succeeded", "failed"]
type CallOutcome = Literal["unfinished", "returned", "denied", "failed"]
type CallRelationship = Literal[
    "listed",
    "descendant",
    "requested",
    "completion_target",
    "creation_result",
    "revision_target",
]


class CallReference(TypedDict):
    run_id: int
    sequence: int


class SkillReference(TypedDict):
    id: str
    revision: int


class DecisionReference(TypedDict):
    event_id: int
    evidence_ids: list[int]
    statement_evidence_id: int | None


class RevisionReference(TypedDict):
    goal_id: int
    revision: int


class DefinitionGrant(TypedDict):
    id: int
    operator_id: int
    action: DefinitionAction
    goal_id: int | None


class GoalResultReference(TypedDict):
    goal_id: int
    revision: int | None
    status: GoalStatus | None
    observation_ids: list[int]
    decision: DecisionReference | None


class WorkCallReference(TypedDict):
    target_work_item_id: int | None
    attempt_id: int | None
    result: Literal["committed", "retrieved"] | None
    reason: str | None


class CallReadReference(CallReference):
    work: NotRequired[WorkCallReference | None]
    outcome: CallOutcome
    committed_event_id: int | None
    retrieved_event_id: int | None
    committed_revision: RevisionReference | None
    retrieved_revision: RevisionReference | None


class RunReadReference(TypedDict):
    run_id: int
    outcome: RunOutcome
    calls: list[CallReadReference]


class CallActivity(CallReference):
    kind: Literal["call"]
    at: str
    tool: HarnessTool
    outcome: CallOutcome
    relationship: CallRelationship


class RevisionReadReference(TypedDict):
    kind: Literal["revision"]
    revision: int
    committing_call: CallReference | None


class ObservationReadReference(TypedDict):
    kind: Literal["observation"]
    evidence_id: int


class DecisionReadReference(DecisionReference):
    kind: Literal["decision"]
    committing_call: CallReference | None


type ActivityReadEntry = (
    RevisionReadReference
    | ObservationReadReference
    | DecisionReadReference
    | CallActivity
)


class ActivityReadReference(TypedDict):
    work_items: NotRequired[list[dict[str, Any]]]
    goal_id: int
    timeline: list[ActivityReadEntry]


type HistoryReadReference = ActivityReadReference | RunReadReference


class RunCall(CallReadReference):
    tool: HarnessTool
    target_goal_id: int | None
    target_revision: int | None
    target_run_id: int | None
    target_skill_id: str | None
    returned_skills: list[SkillReference] | None
    started_at: str
    finished_at: str | None
    returned_goals: list[GoalResultReference] | None
    returned_history: HistoryReadReference | None


class OperatorRun(TypedDict):
    work_grant_id: int | None
    id: int
    owner_user_id: int
    mode: Literal["advisory", "delegated"]
    operator_id: int | None
    completion_grant_id: int | None
    granted_goal_id: int | None
    definition_grant: DefinitionGrant | None
    started_at: str
    finished_at: str | None
    outcome: RunOutcome
    calls: list[RunCall]


def run_read_reference(run: OperatorRun) -> RunReadReference:
    return RunReadReference(
        run_id=run["id"],
        outcome=run["outcome"],
        calls=[
            CallReadReference(
                run_id=call["run_id"],
                sequence=call["sequence"],
                outcome=call["outcome"],
                committed_event_id=call["committed_event_id"],
                retrieved_event_id=call["retrieved_event_id"],
                committed_revision=call["committed_revision"],
                retrieved_revision=call["retrieved_revision"],
                **({"work": call["work"]} if call.get("work") is not None else {}),
            )
            for call in run["calls"]
        ],
    )


class RunNotFoundError(LookupError):
    def __init__(self, run_id: int) -> None:
        super().__init__(f"Run {run_id} was not found.")


def run_row(connection: sqlite3.Connection, run_id: int, owner_id: int) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT run.*, coalesce(grant.operator_id, definition.operator_id, w.operator_id) AS operator_id,
               coalesce(grant.goal_id,w.goal_id) AS granted_goal_id, definition.action AS definition_action,
               definition.goal_id AS definition_goal_id
        FROM operator_runs AS run
        LEFT JOIN work_grants w ON w.id=run.work_grant_id
        LEFT JOIN goal_assignments AS grant ON grant.id = run.completion_grant_id
        LEFT JOIN goal_definition_grants AS definition ON definition.id = run.definition_grant_id
        WHERE run.id = ? AND run.owner_user_id = ?
        """,
        (run_id, owner_id),
    ).fetchone()
    if row is None:
        raise RunNotFoundError(run_id)
    return row


def run_record(row: sqlite3.Row, calls: list[RunCall]) -> OperatorRun:
    definition_grant = None
    if row["definition_grant_id"] is not None:
        definition_grant = DefinitionGrant(
            id=row["definition_grant_id"],
            operator_id=row["operator_id"],
            action=row["definition_action"],
            goal_id=row["definition_goal_id"],
        )
    return OperatorRun(
        id=row["id"],
        owner_user_id=row["owner_user_id"],
        mode="advisory" if row["operator_id"] is None else "delegated",
        operator_id=row["operator_id"],
        completion_grant_id=row["completion_grant_id"],
        granted_goal_id=row["granted_goal_id"],
        definition_grant=definition_grant,
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        outcome=row["outcome"],
        calls=calls,
        work_grant_id=row["work_grant_id"],
    )


def revision_reference(row: sqlite3.Row) -> RevisionReference | None:
    if row["revision_kind"] is None:
        return None
    return RevisionReference(
        goal_id=row["revision_goal_id"], revision=row["saved_revision"]
    )


def run_calls(
    connection: sqlite3.Connection, run_id: int, exclude_sequence: int | None
) -> list[RunCall]:
    skills: dict[int, list[SkillReference]] = defaultdict(list)
    for row in connection.execute(
        """SELECT ref.sequence, skill.skill_key, skill.revision FROM run_call_skills AS ref
           JOIN skill_revisions AS skill ON skill.id = ref.snapshot_id
           WHERE ref.run_id = ? ORDER BY ref.sequence, ref.position""",
        (run_id,),
    ):
        skills[row["sequence"]].append(
            SkillReference(id=row["skill_key"], revision=row["revision"])
        )
    results: dict[int, list[GoalResultReference]] = defaultdict(list)
    for row in connection.execute(
        "SELECT * FROM run_call_goals WHERE run_id = ? ORDER BY sequence, position",
        (run_id,),
    ):
        decision = None
        if row["decision_event_id"] is not None:
            decision = DecisionReference(
                event_id=row["decision_event_id"],
                evidence_ids=json.loads(row["cited_evidence_ids"]),
                statement_evidence_id=row["statement_evidence_id"],
            )
        results[row["sequence"]].append(
            GoalResultReference(
                goal_id=row["goal_id"],
                revision=row["revision"],
                status=row["status"],
                observation_ids=json.loads(row["observation_ids"]),
                decision=decision,
            )
        )
    return [
        RunCall(
            run_id=row["run_id"],
            sequence=row["sequence"],
            work=(
                WorkCallReference(
                    target_work_item_id=row["target_work_item_id"],
                    attempt_id=row["attempt_id"],
                    result=row["work_kind"],
                    reason=row["work_reason"],
                )
                if row["tool"] in ("delegate_work", "retry_work")
                else None
            ),
            tool=row["tool"],
            target_goal_id=row["target_goal_id"],
            target_revision=row["target_revision"],
            target_run_id=row["target_run_id"],
            target_skill_id=row["target_skill_id"],
            returned_skills=skills[row["sequence"]]
            if row["outcome"] == "returned"
            and row["tool"] in ("list_skills", "read_skill")
            else None,
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            outcome=row["outcome"],
            committed_event_id=row["committed_event_id"],
            retrieved_event_id=row["retrieved_event_id"],
            committed_revision=revision_reference(row)
            if row["revision_kind"] == "committed"
            else None,
            retrieved_revision=revision_reference(row)
            if row["revision_kind"] == "retrieved"
            else None,
            returned_goals=results[row["sequence"]]
            if row["outcome"] == "returned"
            and row["returned_history"] is None
            and row["tool"] not in ("list_skills", "read_skill")
            else None,
            returned_history=json.loads(row["returned_history"])
            if row["returned_history"] is not None
            else None,
        )
        for row in connection.execute(
            """
            SELECT call.*, link.goal_id AS revision_goal_id, link.revision AS saved_revision,
                   link.kind AS revision_kind, w.attempt_id,w.kind AS work_kind
            FROM run_calls AS call LEFT JOIN work_call_results w USING (run_id, sequence) LEFT JOIN run_call_revisions AS link USING (run_id, sequence)
            WHERE call.run_id = ? AND call.sequence IS NOT ? ORDER BY call.sequence
            """,
            (run_id, exclude_sequence),
        )
    ]


def related_calls(
    connection: sqlite3.Connection,
    goal_id: int,
    owner_id: int,
    exclude_call: CallReference | None,
) -> tuple[list[CallActivity], dict[int, CallReference], dict[int, CallReference]]:
    rows = connection.execute(
        """
        WITH related(run_id, sequence) AS (
            SELECT run_id, sequence FROM run_calls WHERE resolved_goal_id = :goal_id
            UNION
            SELECT run_id, sequence FROM run_call_goals WHERE goal_id = :goal_id
            UNION
            SELECT run_id, sequence FROM run_call_revisions WHERE goal_id = :goal_id
        )
        SELECT call.*, link.kind AS revision_kind, link.revision AS saved_revision
        FROM related JOIN run_calls AS call USING (run_id, sequence)
        JOIN operator_runs AS run ON run.id = call.run_id AND run.owner_user_id = :owner
        LEFT JOIN run_call_revisions AS link
            ON link.run_id = call.run_id AND link.sequence = call.sequence AND link.goal_id = :goal_id
        """,
        {"goal_id": goal_id, "owner": owner_id},
    )
    calls = []
    decision_commits = {}
    revision_commits = {}
    for row in rows:
        key = CallReference(run_id=row["run_id"], sequence=row["sequence"])
        if key == exclude_call:
            continue
        tool = row["tool"]
        if tool == "complete_goal":
            relationship = "completion_target"
        elif tool == "create_goal" or (
            tool == "create_subgoal" and row["target_goal_id"] != goal_id
        ):
            relationship = "creation_result"
        elif tool == "revise_goal":
            relationship = "revision_target"
        elif tool == "list_goals":
            relationship = "listed"
        elif row["target_goal_id"] == goal_id:
            relationship = "requested"
        else:
            relationship = "descendant"
        calls.append(
            CallActivity(
                **key,
                kind="call",
                at=row["started_at"],
                tool=tool,
                outcome=row["outcome"],
                relationship=relationship,
            )
        )
        if row["committed_event_id"] is not None:
            decision_commits[row["committed_event_id"]] = key
        if row["revision_kind"] == "committed":
            revision_commits[row["saved_revision"]] = key
    return calls, decision_commits, revision_commits


def save_result_references(
    connection: sqlite3.Connection,
    call: CallReference,
    goals: list[GoalResultReference],
) -> None:
    for position, goal in enumerate(goals):
        decision = goal["decision"]
        connection.execute(
            """
            INSERT INTO run_call_goals (
                run_id, sequence, position, goal_id, revision, status, observation_ids,
                decision_event_id, cited_evidence_ids, statement_evidence_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                call["run_id"],
                call["sequence"],
                position,
                goal["goal_id"],
                goal["revision"],
                goal["status"],
                json.dumps(goal["observation_ids"]),
                decision["event_id"] if decision else None,
                json.dumps(decision["evidence_ids"]) if decision else None,
                decision["statement_evidence_id"] if decision else None,
            ),
        )
