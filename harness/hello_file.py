"""The hello-file task, its deterministic workers, and its independent verifier."""

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from harness.client import call, connect
from harness.evidence import Verification

EXPECTED = "hello from the harness"
OUTCOME = "Create result.txt containing hello from the harness, then read it back."
ORIGINAL_PROMPT = (
    "Create result.txt in your workspace containing hello from the harness, then read it back. "
    "Your assigned workspace is accessed through MCP. Call workspace.write_file first, then "
    "workspace.read_file. Write exactly the specified text with no trailing newline."
)


class FileOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["hello-file"] = "hello-file"
    path: Literal["result.txt"] = "result.txt"
    content: str = Field(default=EXPECTED, max_length=4096)

    @field_validator("content")
    @classmethod
    def fits_workspace(cls, value: str) -> str:
        if len(value.encode()) > 4096:
            raise ValueError("Expected content exceeds the workspace limit of 4096 UTF-8 bytes")
        return value

    @property
    def prompt(self) -> str:
        if self.content == EXPECTED:
            return ORIGINAL_PROMPT
        return (
            f"Create {self.path} in your assigned MCP workspace. Call workspace.write_file "
            f"with exactly the content encoded by this JSON string: {json.dumps(self.content)}. "
            "Then call workspace.read_file to read it back."
        )

    @property
    def files(self) -> tuple[str, ...]:
        return (self.path,)

    def verify(self, workspace: Path, calls: list[dict]) -> Verification:
        try:
            actual = (workspace / self.path).read_bytes()
        except FileNotFoundError:
            actual = None
        wrote = read = False
        for event in calls:
            if "result" not in event or event["arguments"]["path"] != self.path:
                continue
            if event["tool"] == "write_file":
                wrote = event["arguments"]["content"] == self.content
                read = False
            elif (
                event["tool"] == "read_file"
                and wrote
                and event["result"].get("content") == self.content
            ):
                read = True
        matches = actual == self.content.encode()
        details = {
            "path": self.path,
            "expected": self.content,
            "actual": actual.decode(errors="replace") if actual is not None else None,
            "file_exists": actual is not None,
            "exact_bytes": matches,
            "observed_write_then_read": read,
        }

        return Verification(matches and read, details, f"exact={matches} | read={read}")


def legacy_verdict(details: dict) -> str:
    return "passed" if details["exact_bytes"] and details["observed_write_then_read"] else "failed"


async def fixture_worker(mode: str, desired: dict):
    outcome = FileOutcome.model_validate(desired)
    if mode == "fixture-missing":
        print(json.dumps({"fixture": mode, "action": "exit without writing"}))
        return
    content = outcome.content
    if mode == "fixture-wrong":
        content = content + "\n" if len(content.encode()) < 4096 else content[:-1]
    elif mode != "fixture-write":
        raise ValueError(f"Unknown fixture worker {mode}")
    async with connect(os.environ["WORKER_MCP_URL"], os.environ["RUN_TOKEN"]) as session:
        for name, args in [
            ("write_file", {"path": outcome.path, "content": content}),
            ("read_file", {"path": outcome.path}),
        ]:
            result = await call(session, name, **args)
            print(json.dumps({"fixture": mode, "tool": name, "result": result}))
