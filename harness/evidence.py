"""Durable run records and journaled access to a run-scoped workspace."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from harness.launch import ExecutionRef, Progress, Worker, WorkerExit

ACTIVE = {"queued", "running"}


def now() -> str:
    return datetime.now(UTC).isoformat()


def save(path: Path, value: dict):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


@dataclass(frozen=True)
class Verification:
    passed: bool
    details: dict
    summary: str


class Run:
    def __init__(self, root: Path, run_id: str):
        self.path = root / str(UUID(run_id))
        self.workspace = self.path / "workspace"
        self.record = self.path / "run.json"
        self.calls = self.path / "tools.jsonl"

    @classmethod
    def create(
        cls,
        root: Path,
        worker: Worker,
        image: str,
        network: str,
        backend: str,
        *,
        prompt: str,
        outcome: dict,
    ):
        run = cls(root, str(uuid4()))
        run.workspace.mkdir(parents=True)
        run.calls.touch()
        run.update(
            run_id=run.path.name,
            created_at=now(),
            status="queued",
            backend=backend,
            worker=worker,
            task=prompt,
            outcome=outcome,
            execution_status="queued",
            verification_status="pending",
            launch={"image": image, "network": network, "name": f"harness-{run.path.name}"},
        )
        return run

    def read(self, trace: bool = False) -> dict:
        data = json.loads(self.record.read_text())
        if trace:
            data["tool_calls"] = self.tool_calls()
            for key, filename in [
                ("worker_stdout", "stdout.jsonl"),
                ("worker_stderr", "stderr.log"),
            ]:
                path = self.path / filename
                data[key] = path.read_text(errors="replace") if path.exists() else None
        return data

    def update(self, **fields):
        data = self.read() if self.record.exists() else {}
        save(self.record, data | fields)

    def tool_calls(self) -> list[dict]:
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def progress(self, fact: Progress):
        fields = dict(fact.details)
        if fact.running:
            fields.update(status="running", execution_status="running")
        if fact.timed_out:
            fields["timed_out"] = True
        self.update(**fields)

    def exited(self, fact: WorkerExit):
        status = "succeeded" if fact.exit_code == 0 else "failed"
        self.update(
            exit_code=fact.exit_code,
            started_at=fact.started_at,
            exited_at=fact.exited_at,
            execution_status="timed out" if self.read().get("timed_out") else status,
        )

    def finish(self, result: Verification):
        data = self.read()
        status = {"timed out": "timed out", "failed": "worker failed"}.get(
            data["execution_status"], "passed" if result.passed else "verification failed"
        )
        self.update(
            status=status,
            verification_status="passed" if result.passed else "failed",
            verification=result.details | {"checked_at": now()},
            cleanup="pending",
            summary=f"{self.path.name} | {status} | exit={data['exit_code']} | {result.summary}",
        )


def execution_ref(data: dict) -> ExecutionRef:
    # Existing records store backend identifiers at top level under *_id.
    ids = {k: v for k, v in data.items() if k.endswith("_id") and k != "run_id"}
    return ExecutionRef(data["run_id"], data["launch"]["name"], ids)


@dataclass(frozen=True)
class Workspace:
    directory: Path
    calls: Path
    allowed_files: tuple[str, ...]

    def file_tool(self, tool: str, path: str, content: str | None = None) -> dict:
        args = {"path": path}
        if content is not None:
            args["content"] = content
        event = {"at": now(), "tool": tool, "arguments": args}
        try:
            if path not in self.allowed_files:
                raise ValueError("Path is outside this run's workspace scope")
            file = self.directory / path
            if tool == "write_file":
                encoded = content.encode("utf-8")
                if len(encoded) > 4096:
                    raise ValueError("The file exceeds 4096 bytes")
                file.write_bytes(encoded)
                result = {"bytes_written": len(encoded)}
            elif tool == "read_file":
                result = {"content": file.read_bytes().decode("utf-8")}
            else:
                raise ValueError("Unknown file tool")
            event["result"] = result
            return result
        except (OSError, ValueError) as exc:
            event["error"] = str(exc)
            raise
        finally:
            with self.calls.open("a") as stream:
                stream.write(json.dumps(event) + "\n")
