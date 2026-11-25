"""Workspace records and their persistence rules."""

from typing import Literal

type GoalStatus = Literal["draft", "active", "paused", "completed", "revoked"]
