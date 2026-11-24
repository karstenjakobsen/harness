"""Durable evidence for the single-file task. Only the harness mounts this directory."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

EXPECTED = "hello from the harness"
TASK = (
    "Create result.txt in your workspace containing hello from the harness, then read it back. "
    "Your assigned workspace is accessed through MCP. Call workspace.write_file first, then "
    "workspace.read_file. Write exactly the specified text "
    "with no trailing newline."
)
Worker = Literal["codex", "fixture-write", "fixture-missing", "fixture-wrong"]
ACTIVE = {"queued", "running"}


def now() -> str:
    return datetime.now(UTC).isoformat()


def save(path: Path, value: dict):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


class Run:
    def __init__(self, root: Path, run_id: str):
        self.path = root / str(UUID(run_id))
        self.file = self.path / "workspace" / "result.txt"
        self.record = self.path / "run.json"
        self.calls = self.path / "tools.jsonl"

    @classmethod
    def create(cls, root: Path, worker: Worker, image: str, network: str, backend: str = "docker"):
        run = cls(root, str(uuid4()))
        run.file.parent.mkdir(parents=True)
        run.calls.touch()
        run.update(
            run_id=run.path.name,
            created_at=now(),
            status="queued",
            backend=backend,
            worker=worker,
            task=TASK,
            launch={"image": image, "network": network, "name": f"harness-{run.path.name}"},
        )
        return run

    def read(self, trace: bool = False) -> dict:
        data = json.loads(self.record.read_text())
        if trace:
            data["tool_calls"] = [json.loads(line) for line in self.calls.read_text().splitlines()]
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

    def file_tool(self, tool: str, path: str, content: str | None = None) -> dict:
        args = {"path": path}
        if content is not None:
            args["content"] = content
        event = {"at": now(), "tool": tool, "arguments": args}
        try:
            if path != "result.txt":
                raise ValueError("This workspace exposes only result.txt")
            if tool == "write_file":
                encoded = content.encode("utf-8")
                if len(encoded) > 4096:
                    raise ValueError("The file exceeds 4096 bytes")
                self.file.write_bytes(encoded)
                result = {"bytes_written": len(encoded)}
            elif tool == "read_file":
                result = {"content": self.file.read_bytes().decode("utf-8")}
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

    def finish(self, state: dict, timed_out: bool):
        # The caller has confirmed worker exit and saved both log streams.
        try:
            actual = self.file.read_bytes()
        except FileNotFoundError:
            actual = None
        matches = actual == EXPECTED.encode()
        read_back = False
        wrote_expected = False
        for line in self.calls.read_text().splitlines():
            call = json.loads(line)
            if "result" not in call:
                continue
            if call["tool"] == "write_file":
                wrote_expected = call["arguments"]["content"] == EXPECTED
                read_back = False
            elif wrote_expected and call["result"].get("content") == EXPECTED:
                read_back = True
        code = state["ExitCode"]
        if timed_out:
            status = "timed out"
        elif code != 0:
            status = "worker failed"
        elif not (matches and read_back):
            status = "verification failed"
        else:
            status = "passed"
        verification = {
            "checked_at": now(),
            "path": "result.txt",
            "expected": EXPECTED,
            "actual": actual.decode("utf-8", errors="replace") if actual is not None else None,
            "file_exists": actual is not None,
            "exact_bytes": matches,
            "observed_write_then_read": read_back,
        }
        self.update(
            status=status,
            exit_code=code,
            started_at=state["StartedAt"],
            exited_at=state["FinishedAt"],
            verification=verification,
            cleanup="pending",
            summary=(
                f"{self.path.name} | {status} | exit={code} | exact={matches} | read={read_back}"
            ),
        )
