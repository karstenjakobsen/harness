"""Persist tool attempts and the references exposed in their results."""

import json
import sqlite3
from collections import defaultdict
from typing import Literal, TypedDict

from . import GoalStatus

type HarnessTool = Literal[
    "list_goals", "get_goal_tree", "get_goal_progress", "complete_goal"
]
type RunOutcome = Literal["unfinished", "succeeded", "failed"]
type CallOutcome = Literal["unfinished", "returned", "denied", "failed"]
type CallRelationship = Literal[
    "listed", "descendant", "requested", "completion_target"
]


class CallReference(TypedDict):
    run_id: int
    sequence: int


class DecisionReference(TypedDict):
    event_id: int
    evidence_ids: list[int]
    statement_evidence_id: int | None


class GoalResultReference(TypedDict):
    goal_id: int
    revision: int | None
    status: GoalStatus | None
    observation_ids: list[int]
    decision: DecisionReference | None


class RunCall(CallReference):
    tool: HarnessTool
    target_goal_id: int | None
    target_revision: int | None
    started_at: str
    finished_at: str | None
    outcome: CallOutcome
    returned_goals: list[GoalResultReference] | None
    committed_event_id: int | None
    retrieved_event_id: int | None


class OperatorRun(TypedDict):
    id: int
    owner_user_id: int
    mode: Literal["advisory", "delegated"]
    operator_id: int | None
    completion_grant_id: int | None
    granted_goal_id: int | None
    started_at: str
    finished_at: str | None
    outcome: RunOutcome
    calls: list[RunCall]


class CallActivity(CallReference):
    kind: Literal["call"]
    at: str
    tool: HarnessTool
    outcome: CallOutcome
    relationship: CallRelationship


class RunNotFoundError(LookupError):
    def __init__(self, run_id: int) -> None:
        super().__init__(f"Run {run_id} was not found.")


def run_row(connection: sqlite3.Connection, run_id: int, owner_id: int) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT run.*, grant.operator_id, grant.goal_id AS granted_goal_id
        FROM operator_runs AS run
        LEFT JOIN goal_assignments AS grant ON grant.id = run.completion_grant_id
        WHERE run.id = ? AND run.owner_user_id = ?
        """,
        (run_id, owner_id),
    ).fetchone()
    if row is None:
        raise RunNotFoundError(run_id)
    return row


def run_record(row: sqlite3.Row, calls: list[RunCall]) -> OperatorRun:
    return OperatorRun(
        id=row["id"],
        owner_user_id=row["owner_user_id"],
        mode="advisory" if row["completion_grant_id"] is None else "delegated",
        operator_id=row["operator_id"],
        completion_grant_id=row["completion_grant_id"],
        granted_goal_id=row["granted_goal_id"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        outcome=row["outcome"],
        calls=calls,
    )


def run_calls(connection: sqlite3.Connection, run_id: int) -> list[RunCall]:
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
            tool=row["tool"],
            target_goal_id=row["target_goal_id"],
            target_revision=row["target_revision"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            outcome=row["outcome"],
            committed_event_id=row["committed_event_id"],
            retrieved_event_id=row["retrieved_event_id"],
            returned_goals=results[row["sequence"]]
            if row["outcome"] == "returned"
            else None,
        )
        for row in connection.execute(
            "SELECT * FROM run_calls WHERE run_id = ? ORDER BY sequence", (run_id,)
        )
    ]


def related_calls(
    connection: sqlite3.Connection, goal_id: int, owner_id: int
) -> tuple[list[CallActivity], dict[int, CallReference]]:
    rows = connection.execute(
        """
        WITH related(run_id, sequence) AS (
            SELECT run_id, sequence FROM run_calls WHERE target_goal_id = :goal_id
            UNION
            SELECT run_id, sequence FROM run_call_goals WHERE goal_id = :goal_id
        )
        SELECT call.* FROM related JOIN run_calls AS call USING (run_id, sequence)
        JOIN operator_runs AS run ON run.id = call.run_id AND run.owner_user_id = :owner
        """,
        {"goal_id": goal_id, "owner": owner_id},
    )
    calls = []
    commits = {}
    for row in rows:
        tool = row["tool"]
        if tool == "complete_goal":
            relationship = "completion_target"
        elif tool == "list_goals":
            relationship = "listed"
        elif row["target_goal_id"] == goal_id:
            relationship = "requested"
        else:
            relationship = "descendant"
        key = CallReference(run_id=row["run_id"], sequence=row["sequence"])
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
            commits[row["committed_event_id"]] = key
    return calls, commits


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
