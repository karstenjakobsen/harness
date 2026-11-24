"""Types shared by the engine and its execution backends."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypedDict

Worker = Literal["codex", "fixture-write", "fixture-missing", "fixture-wrong"]


@dataclass(frozen=True)
class ExecutionRef:
    run_id: str
    name: str
    ids: Mapping[str, str]


@dataclass(frozen=True)
class LaunchRequest:
    ref: ExecutionRef
    image: str
    network: str
    worker: Worker
    uid: int
    deadline: float
    env: dict[str, str] = field(repr=False)
    auth_file: str | None = field(repr=False)

    def worker_env(self) -> dict[str, str]:
        # Reattaching to an existing worker does not require credentials to launch a new one.
        if self.worker == "codex" and not (self.auth_file or self.env.get("CODEX_API_KEY")):
            raise ValueError("Set CODEX_AUTH_FILE or CODEX_API_KEY for the Codex worker")
        return self.env.copy()


class Diagnostics(TypedDict, total=False):
    container_id: str
    image_id: str
    job_id: str
    evaluation_id: str
    allocation_id: str
    node_id: str
    allocation_status: str
    task_events: list[dict]


@dataclass(frozen=True)
class Progress:
    details: Diagnostics = field(default_factory=dict)
    running: bool = False
    timed_out: bool = False


type Report = Callable[[Progress], None]


@dataclass(frozen=True)
class WorkerExit:
    exit_code: int
    started_at: str
    exited_at: str


class ExecutionBackend(Protocol):
    name: str

    async def wait(self, request: LaunchRequest, report: Report) -> WorkerExit: ...
    async def logs(self, ref: ExecutionRef, stream: str) -> bytes: ...
    async def cleanup(self, ref: ExecutionRef) -> None: ...
    async def close(self) -> None: ...
