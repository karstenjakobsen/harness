import sqlite3
from typing import TypedDict

from ..database import ADMIN_USER_ID, WorkspaceDatabase


class User(TypedDict):
    id: str
    display_name: str
    created_at: str
    deleted_at: str | None


class Operator(TypedDict):
    id: int
    owner_user_id: str
    name: str
    mission: str | None
    created_at: str
    deleted_at: str | None


class AccountNotFoundError(LookupError):
    """The requested workspace user or operator is missing or deleted."""


class AccountConflictError(RuntimeError):
    """The requested change conflicts with an existing identity or registration."""


class AccountValidationError(ValueError):
    """An account field has an invalid value."""


def _text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AccountValidationError(f"{field} must contain text.")
    return value.strip()


def _operator_id(value: int) -> int:
    if type(value) is not int or not -(2**63) <= value < 2**63:
        raise AccountValidationError("Operator ID must be a signed 64-bit integer.")
    return value


def _user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        display_name=row["display_name"],
        created_at=row["created_at"],
        deleted_at=row["deleted_at"],
    )


def _operator(row: sqlite3.Row) -> Operator:
    return Operator(
        id=row["id"],
        owner_user_id=row["owner_user_id"],
        name=row["name"],
        mission=row["mission"],
        created_at=row["created_at"],
        deleted_at=row["deleted_at"],
    )


def _get_user(connection: sqlite3.Connection, user_id: str) -> User:
    row = connection.execute(
        "SELECT * FROM users WHERE id = ? AND deleted_at IS NULL",
        (user_id,),
    ).fetchone()
    if row is None:
        raise AccountNotFoundError(f"User {user_id!r} was not found.")
    return _user(row)


class UserAPI(WorkspaceDatabase):
    """Manage users in a workspace. Deleted user IDs remain reserved."""

    def create_user(self, user_id: str, display_name: str | None = None) -> User:
        user_id = _text(user_id, "User ID")
        name = user_id if display_name is None else _text(display_name, "Display name")
        with self._write() as connection:
            row = connection.execute(
                """INSERT INTO users (id, display_name) VALUES (?, ?)
                    ON CONFLICT (id) DO NOTHING RETURNING *""",
                (user_id, name),
            ).fetchone()
            if row is None:
                raise AccountConflictError(
                    f"User ID {user_id!r} is already in use or reserved."
                )
            return _user(row)

    def get_user(self, user_id: str) -> User:
        with self._connection(read_only=True) as connection:
            return _get_user(connection, _text(user_id, "User ID"))

    def list_users(self) -> list[User]:
        with self._connection(read_only=True) as connection:
            rows = connection.execute(
                "SELECT * FROM users WHERE deleted_at IS NULL ORDER BY id"
            )
            return [_user(row) for row in rows]

    def update_user(self, user_id: str, display_name: str) -> User:
        user_id = _text(user_id, "User ID")
        name = _text(display_name, "Display name")
        with self._write() as connection:
            row = connection.execute(
                """UPDATE users SET display_name = ? WHERE id = ? AND deleted_at IS NULL
                    RETURNING *""",
                (name, user_id),
            ).fetchone()
            if row is None:
                raise AccountNotFoundError(f"User {user_id!r} was not found.")
            return _user(row)

    def delete_user(self, user_id: str) -> User:
        user_id = _text(user_id, "User ID")
        if user_id == ADMIN_USER_ID:
            raise AccountConflictError("The system user admin cannot be deleted.")
        with self._write() as connection:
            _get_user(connection, user_id)
            registered = connection.execute(
                "SELECT 1 FROM operators WHERE owner_user_id = ? AND deleted_at IS NULL LIMIT 1",
                (user_id,),
            ).fetchone()
            if registered is not None:
                raise AccountConflictError(
                    f"User {user_id!r} still owns a registered operator."
                )
            row = connection.execute(
                "UPDATE users SET deleted_at = CURRENT_TIMESTAMP WHERE id = ? RETURNING *",
                (user_id,),
            ).fetchone()
            return _user(row)


class OperatorAPI(WorkspaceDatabase):
    """Register workspace operators and retain their ownership and assignment history."""

    def register_operator(
        self,
        name: str,
        owner_user_id: str | None = None,
        *,
        mission: str | None = None,
    ) -> Operator:
        name = _text(name, "Operator name")
        owner_user_id = (
            ADMIN_USER_ID if owner_user_id is None else _text(owner_user_id, "User ID")
        )
        if mission is not None:
            mission = _text(mission, "Mission")
        with self._write() as connection:
            _get_user(connection, owner_user_id)
            row = connection.execute(
                """INSERT INTO operators (owner_user_id, name, mission) VALUES (?, ?, ?)
                    RETURNING *""",
                (owner_user_id, name, mission),
            ).fetchone()
            return _operator(row)

    def get_operator(self, operator_id: int) -> Operator:
        with self._connection(read_only=True) as connection:
            row = connection.execute(
                "SELECT * FROM operators WHERE id = ? AND deleted_at IS NULL",
                (_operator_id(operator_id),),
            ).fetchone()
            if row is None:
                raise AccountNotFoundError(f"Operator {operator_id} was not found.")
            return _operator(row)

    def list_operators(self, owner_user_id: str | None = None) -> list[Operator]:
        if owner_user_id is not None:
            owner_user_id = _text(owner_user_id, "User ID")
        with self._connection(read_only=True) as connection:
            rows = connection.execute(
                """SELECT * FROM operators WHERE deleted_at IS NULL
                    AND (:owner IS NULL OR owner_user_id = :owner) ORDER BY id""",
                {"owner": owner_user_id},
            )
            return [_operator(row) for row in rows]

    def unregister_operator(self, operator_id: int) -> Operator:
        """Soft-delete the operator and release its active goal assignments."""
        with self._write() as connection:
            row = connection.execute(
                """UPDATE operators SET deleted_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND deleted_at IS NULL RETURNING *""",
                (_operator_id(operator_id),),
            ).fetchone()
            if row is None:
                raise AccountNotFoundError(f"Operator {operator_id} was not found.")
            connection.execute(
                "UPDATE goal_assignments SET released_at = ? WHERE operator_id = ? AND released_at IS NULL",
                (row["deleted_at"], operator_id),
            )
            return _operator(row)
