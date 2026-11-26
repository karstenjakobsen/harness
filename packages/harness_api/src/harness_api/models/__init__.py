"""Workspace records and their persistence rules."""

import secrets
from pathlib import Path
from typing import Literal

from ..database import WorkspaceDatabase

type GoalStatus = Literal["draft", "active", "paused", "completed", "revoked"]


class GoalValidationError(ValueError):
    """A goal operation received invalid input."""


class GoalConflictError(RuntimeError):
    """The current state of a goal prevents the requested operation."""


class WorkspaceModel(WorkspaceDatabase):
    """Shared workspace access rules for domain models."""

    @property
    def owner_http_token_file(self) -> Path:
        return self._path.with_name(self._path.name + ".owner-token")

    def permits_owner_http(self, bearer: bytes) -> bool:
        with self._connection("ro") as connection:
            if not connection.execute("SELECT 1 FROM worker_configuration").fetchone():
                return True
        try:
            expected = self.owner_http_token_file.read_bytes()
        except OSError:
            return False
        return bool(expected) and secrets.compare_digest(bearer, expected)
