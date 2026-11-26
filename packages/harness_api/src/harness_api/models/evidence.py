"""Owner reports and the count-distinct-reported-dates assessment."""

import json
import sqlite3
from datetime import UTC, datetime
from typing import Literal, NotRequired, TypedDict

from ..database import utc_timestamp

type EvidenceSource = Literal[
    "owner_confirmation",
    "owner_supplied_reference",
    "unattributed_confirmation",
    "unattributed_reference",
    "worker_result",
]


class EvidenceStatement(TypedDict):
    worker_attempt_id: NotRequired[int]
    worker_allocation_id: NotRequired[str]
    requesting_operator_id: NotRequired[int]
    evidence_kind: EvidenceSource
    evidence: str
    reported_date: NotRequired[str | None]


class Evidence(TypedDict):
    worker_attempt_id: NotRequired[int]
    worker_allocation_id: NotRequired[str]
    requesting_operator_id: NotRequired[int]
    evidence_id: int
    goal_id: int
    revision: int
    source: EvidenceSource
    evidence: str
    reported_date: str | None
    occurred_at: str
    recorded_at: str
    submitted_by: int | None
    observed_by: int | None
    requested_by: int | None


class ReportedDay(TypedDict):
    reported_date: str
    evidence_ids: list[int]


class DateAssessment(TypedDict):
    rule: Literal["count_distinct_reported_dates"] | None
    result: Literal["met", "unmet", "unavailable"]
    count: int | None
    target: int | None
    window_start: str | None
    window_end: str | None
    days: list[ReportedDay]
    evidence: list[Evidence]


def evidence_record(row: sqlite3.Row) -> Evidence:
    payload: EvidenceStatement = json.loads(row["payload"])
    source = payload["evidence_kind"]
    record = Evidence(
        evidence_id=row["id"],
        goal_id=row["goal_id"],
        revision=row["revision"],
        source=source,
        evidence=payload["evidence"],
        reported_date=payload.get("reported_date"),
        occurred_at=row["occurred_at"],
        recorded_at=row["recorded_at"],
        submitted_by=row["actor_user_id"],
        observed_by=row["actor_user_id"] if source == "owner_confirmation" else None,
        requested_by=None,
    )
    if source == "worker_result":
        record.update(
            worker_attempt_id=payload["worker_attempt_id"],
            worker_allocation_id=payload["worker_allocation_id"],
            requesting_operator_id=payload["requesting_operator_id"],
        )
    return record


def goal_evidence(connection: sqlite3.Connection, goal_id: int) -> list[Evidence]:
    rows = connection.execute(
        "SELECT * FROM goal_events WHERE goal_id = ? AND kind = 'observation' ORDER BY id",
        (goal_id,),
    )
    return [evidence_record(row) for row in rows]


def add_evidence(
    connection: sqlite3.Connection,
    goal_id: int,
    revision: int,
    actor_user_id: int | None,
    payload: EvidenceStatement,
    retry_key: str | None = None,
) -> Evidence:
    timestamp = utc_timestamp()
    row = connection.execute(
        """
        INSERT INTO goal_events (
            goal_id, revision, kind, actor_user_id, payload, retry_key, occurred_at, recorded_at
        )
        VALUES (?, ?, 'observation', ?, ?, ?, ?, ?) RETURNING *
    """,
        (
            goal_id,
            revision,
            actor_user_id,
            json.dumps(payload),
            retry_key,
            timestamp,
            timestamp,
        ),
    ).fetchone()
    return evidence_record(row)


def is_future_dated(record: Evidence) -> bool:
    """Compare the claimed day to the UTC day Harness received the report."""
    day = record["reported_date"]
    if day is None:
        return False
    recorded_at = datetime.fromisoformat(record["recorded_at"])
    if recorded_at.tzinfo is not None:
        recorded_at = recorded_at.astimezone(UTC)
    return day > recorded_at.date().isoformat()


def assess_dates(
    records: list[Evidence], target: int | None, window: tuple[str, str] | None
) -> DateAssessment:
    if target is None:
        return DateAssessment(
            rule=None,
            result="unavailable",
            count=None,
            target=None,
            window_start=None,
            window_end=None,
            days=[],
            evidence=records,
        )
    by_date: dict[str, list[int]] = {}
    for record in records:
        day = record["reported_date"]
        if (
            record["source"] != "owner_confirmation"
            or day is None
            or is_future_dated(record)
        ):
            continue
        if window is not None and not window[0] <= day <= window[1]:
            continue
        by_date.setdefault(day, []).append(record["evidence_id"])
    start, end = window or (None, None)
    return DateAssessment(
        rule="count_distinct_reported_dates",
        result="met" if len(by_date) >= target else "unmet",
        count=len(by_date),
        target=target,
        window_start=start,
        window_end=end,
        days=[
            ReportedDay(reported_date=day, evidence_ids=by_date[day])
            for day in sorted(by_date)
        ],
        evidence=records,
    )
