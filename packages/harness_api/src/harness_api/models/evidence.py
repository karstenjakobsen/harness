"""Owner reports and the count-distinct-reported-dates assessment."""

import json
import sqlite3
from typing import Literal, NotRequired, TypedDict

type EvidenceSource = Literal[
    "owner_confirmation",
    "owner_supplied_reference",
    "unattributed_confirmation",
    "unattributed_reference",
]


class EvidenceStatement(TypedDict):
    evidence_kind: EvidenceSource
    evidence: str
    reported_date: NotRequired[str | None]


class Evidence(TypedDict):
    evidence_id: int
    goal_id: int
    revision: int
    source: EvidenceSource
    evidence: str
    reported_date: str | None
    occurred_at: str
    recorded_at: str
    submitted_by: str | None
    observed_by: str | None
    requested_by: str | None


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


def submitted_by(actor: str, source: EvidenceSource) -> str | None:
    if source in ("unattributed_confirmation", "unattributed_reference"):
        return None
    return actor


def evidence_record(row: sqlite3.Row) -> Evidence:
    payload: EvidenceStatement = json.loads(row["payload"])
    source = payload["evidence_kind"]
    return Evidence(
        evidence_id=row["id"],
        goal_id=row["goal_id"],
        revision=row["revision"],
        source=source,
        evidence=payload["evidence"],
        reported_date=payload.get("reported_date"),
        occurred_at=row["occurred_at"],
        recorded_at=row["recorded_at"],
        submitted_by=submitted_by(row["actor"], source),
        observed_by=row["actor"] if source == "owner_confirmation" else None,
        requested_by=None,
    )


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
    actor: str,
    payload: EvidenceStatement,
    retry_key: str | None = None,
) -> Evidence:
    row = connection.execute(
        """
        INSERT INTO goal_events (goal_id, revision, kind, actor, payload, retry_key)
        VALUES (?, ?, 'observation', ?, ?, ?) RETURNING *
    """,
        (goal_id, revision, actor, json.dumps(payload), retry_key),
    ).fetchone()
    return evidence_record(row)


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
    supporting = []
    for record in records:
        day = record["reported_date"]
        if record["source"] != "owner_confirmation" or day is None:
            continue
        if window is not None and not window[0] <= day <= window[1]:
            continue
        by_date.setdefault(day, []).append(record["evidence_id"])
        supporting.append(record)
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
        evidence=supporting,
    )
