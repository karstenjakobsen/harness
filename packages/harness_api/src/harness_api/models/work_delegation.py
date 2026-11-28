"""Shared work-delegation authority for model operations and run binding."""

import sqlite3
from typing import TypedDict, cast


class WorkDelegationGrant(TypedDict):
    id: int
    operator_id: int
    goal_id: int
    granted_at: str
    withdrawn_at: str | None


def active_delegation_grant(
    connection: sqlite3.Connection, grant_id: int, owner_id: int
) -> WorkDelegationGrant | None:
    row = connection.execute(
        """SELECT grant.* FROM work_delegation_grants AS grant
           JOIN operators AS operator ON operator.id = grant.operator_id
           JOIN goals AS goal ON goal.id = grant.goal_id
           WHERE grant.id = ? AND grant.withdrawn_at IS NULL
             AND operator.owner_user_id = ? AND operator.deleted_at IS NULL
             AND goal.owner_user_id = operator.owner_user_id AND goal.deleted_at IS NULL""",
        (grant_id, owner_id),
    ).fetchone()
    return cast(WorkDelegationGrant, dict(row)) if row is not None else None
