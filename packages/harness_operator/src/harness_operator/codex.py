import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TextIO

from pydantic import ConfigDict, TypeAdapter, with_config

from harness_api import GoalDefinition

OPERATOR_INSTRUCTIONS = """\
You are the user's goal operator. Treat goals as flexible guidelines.
Read relevant workspace files when helpful and suggest a small next step.
Use the harness_mcp list_goals tool to find saved goal IDs. For questions about a
plan and its subgoals or completion decisions, call get_goal_tree with the goal ID.
For progress questions call get_goal_progress. Use its assessed revision, count,
target and lifecycle status. Cite the qualifying evidence IDs listed under days.
The evidence list includes every report considered. When explaining a report
that did not count, cite its ID and use its source, dates and the assessed rule.
State when attribution or automatic assessment is unavailable.
Use the returned records to answer. List each goal on its own line with its status
and the relevant timing or evidence. Draft, active, and paused goals are open.
Attribute completion statements according to their saved provenance.
If the tool fails, say that you could not retrieve the goals.
Keep this turn advisory. Describe goal changes as proposals.
"""

DRAFT_INSTRUCTIONS = """\
Draft a goal from the user's request. Keep the definition light and provisional.
Decide duration and assessment type independently.
Duration describes the kind of goal: one_time for a result verified once, or standing for ongoing maintenance.
Use duration_days for the stated time window in whole days. For "track food for seven days", use 7.
Leave duration_days null if the user has not specified a time window.
Use target_distinct_dates for an explicit count of distinct dates confirmed by the owner.
Use window_start (YYYY-MM-DD) for the stated start of a window with a duration.
For seven distinct dates within fourteen days, set target_distinct_dates to 7 and duration_days to 14.
Assessment is objective for a checkable result, judgment for human judgment, or mixed if both matter.
Describe the desired outcome, what would count as success, and how to assess it when clear.
Leave uncertain fields null. Ask one focused question if the goal needs clarification.
Preserve the user's intent and leave review timing unspecified unless the user supplied it.
Return a draft definition only. Do not carry out the goal or run checks.
"""


@with_config(ConfigDict(extra="forbid", strict=True))
class GoalDraft(GoalDefinition):
    title: str
    clarification: str | None


GOAL_DRAFT = TypeAdapter(GoalDraft)


def exit_code(returncode: int) -> int:
    return returncode if returncode >= 0 else 128 - returncode


def register_codex() -> int:
    result = subprocess.run(["codex", "login", "--device-auth"], check=False)
    return exit_code(result.returncode)


def _run_codex(
    message: str,
    instructions: str,
    *,
    schema: Path | None = None,
    trace: TextIO | None = None,
    reply_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        "codex",
        "--ask-for-approval",
        "never",
        "exec",
        "--ignore-user-config",
        "-c",
        f"mcp_servers.harness_mcp.command={json.dumps(sys.executable, ensure_ascii=False)}",
        "-c",
        'mcp_servers.harness_mcp.args=["-P", "-m", "harness_mcp.server"]',
        "-c",
        f"mcp_servers.harness_mcp.cwd={json.dumps(str(Path.cwd()), ensure_ascii=False)}",
        "-c",
        "mcp_servers.harness_mcp.required=true",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--skip-git-repo-check",
    ]
    if schema is not None:
        command.extend(["--output-schema", str(schema)])
    if reply_path is not None:
        command.extend(["--json", "--output-last-message", str(reply_path)])
    result = subprocess.run(
        [*command, "-"],
        input=f"{instructions}\nUser message:\n{message}",
        encoding="utf-8",
        stdout=subprocess.PIPE if schema is not None else trace,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode and result.stderr:
        sys.stderr.write(result.stderr)
    return result


def ask_codex(message: str, trace_file: Path | None = None) -> int:
    if trace_file is None:
        return exit_code(_run_codex(message, OPERATOR_INSTRUCTIONS).returncode)
    with (
        open(
            trace_file,
            "x",
            encoding="utf-8",
            opener=lambda path, flags: os.open(path, flags, 0o600),
        ) as trace,
        TemporaryDirectory() as directory,
    ):
        reply_path = Path(directory) / "reply.txt"
        result = _run_codex(
            message, OPERATOR_INSTRUCTIONS, trace=trace, reply_path=reply_path
        )
        if result.returncode == 0:
            print(reply_path.read_text(encoding="utf-8").rstrip())
    return exit_code(result.returncode)


def generate_goal_draft(message: str) -> GoalDraft:
    with TemporaryDirectory(prefix="harness-goal-") as directory:
        schema = Path(directory) / "draft.json"
        schema.write_text(json.dumps(GOAL_DRAFT.json_schema()), encoding="utf-8")
        result = _run_codex(message, DRAFT_INSTRUCTIONS, schema=schema)
    result.check_returncode()
    return GOAL_DRAFT.validate_json(result.stdout)
