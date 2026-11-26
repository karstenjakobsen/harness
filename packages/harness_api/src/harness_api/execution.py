"""The workload contract shared by execution callers and scheduler adapters."""

import re
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class WorkloadSpec:
    image: str
    # The first element names the executable inside the image.
    argv: tuple[str, ...]

    def __post_init__(self):
        if not re.fullmatch(r"[^@\s]+@sha256:[a-f0-9]{64}", self.image):
            raise ValueError("The workload image must be pinned by SHA-256 digest.")
        if (
            not isinstance(self.argv, tuple)
            or not self.argv
            or not all(isinstance(arg, str) and "\x00" not in arg for arg in self.argv)
            or not self.argv[0]
        ):
            raise ValueError(
                "argv must be a tuple of strings beginning with an executable."
            )


type ExecutionState = Literal[
    "pending", "running", "succeeded", "failed", "stopped", "unknown"
]


@dataclass(frozen=True)
class WorkloadStatus:
    state: ExecutionState
    job_id: str
    allocation_id: str | None = None
    exit_code: int | None = None
    replacement_allocation_ids: tuple[str, ...] = ()


class ExecutionBackend(Protocol):
    def handle(self, run_id: str) -> str: ...
    def lookup(self, run_id: str, spec: WorkloadSpec) -> WorkloadStatus: ...
    def start(self, run_id: str, spec: WorkloadSpec) -> str: ...
    def inspect(self, handle: str) -> WorkloadStatus: ...
    def stop(self, handle: str) -> None: ...
