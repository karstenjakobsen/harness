"""Workspace records and their persistence rules."""

from typing import Literal

type GoalStatus = Literal["draft", "active", "paused", "completed", "revoked"]


class GoalValidationError(ValueError):
    """A goal operation received invalid input."""


class GoalConflictError(RuntimeError):
    """The current state of a goal prevents the requested operation."""
