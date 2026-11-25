import json
import os
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TextIO

from pydantic import ConfigDict, TypeAdapter, with_config

from harness_api import GoalAPI, GoalDefinition

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
"""

ADVISORY_INSTRUCTIONS = "Keep this turn advisory. Describe goal changes as proposals.\n"

DELEGATED_INSTRUCTIONS = """\
The owner delegated completion of subgoal {goal_id} for this session.
Read that subgoal's current definition with get_goal_tree and its observations
with get_goal_progress before deciding. Weigh the evidence and its provenance
against the revision's criteria. If the user asks you to act and you judge the
evidence sufficient, call complete_goal with the revision you reviewed, the
supporting evidence IDs and your rationale. If evidence is insufficient, leave
the goal open and explain what is missing or ask for clarification. Report the
result and distinguish the cited evidence from your decision.
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
    completion_grant_id: int | None = None,
    run_id: int | None = None,
) -> subprocess.CompletedProcess[str]:
    mcp_args = ["-P", "-m", "harness_mcp.server"]
    if run_id is not None:
        mcp_args.extend(["--run-id", str(run_id)])
    if completion_grant_id is not None:
        mcp_args.extend(["--completion-grant", str(completion_grant_id)])
    command = [
        "codex",
        "--ask-for-approval",
        "never",
        "exec",
        "--ignore-user-config",
        "-c",
        f"mcp_servers.harness_mcp.command={json.dumps(sys.executable, ensure_ascii=False)}",
        "-c",
        f"mcp_servers.harness_mcp.args={json.dumps(mcp_args)}",
        "-c",
        f"mcp_servers.harness_mcp.cwd={json.dumps(str(Path.cwd()), ensure_ascii=False)}",
        "-c",
        "mcp_servers.harness_mcp.required=true",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--skip-git-repo-check",
    ]
    if completion_grant_id is not None:
        command.extend(
            [
                "-c",
                'mcp_servers.harness_mcp.tools.complete_goal.approval_mode="approve"',
            ]
        )
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


def ask_codex(
    message: str,
    trace_file: Path | None = None,
    *,
    completion_grant_id: int | None = None,
) -> int:
    api = GoalAPI()
    run = api.start_run(completion_grant_id)
    instructions = OPERATOR_INSTRUCTIONS + (
        ADVISORY_INSTRUCTIONS
        if run["mode"] == "advisory"
        else DELEGATED_INSTRUCTIONS.format(goal_id=run["granted_goal_id"])
    )
    try:
        with ExitStack() as stack:
            trace = None
            reply_path = None
            if trace_file is not None:
                trace = stack.enter_context(
                    open(
                        trace_file,
                        "x",
                        encoding="utf-8",
                        opener=lambda path, flags: os.open(path, flags, 0o600),
                    )
                )
                reply_path = (
                    Path(stack.enter_context(TemporaryDirectory())) / "reply.txt"
                )
            result = _run_codex(
                message,
                instructions,
                trace=trace,
                reply_path=reply_path,
                completion_grant_id=completion_grant_id,
                run_id=run["id"],
            )
            if reply_path is not None and result.returncode == 0:
                print(reply_path.read_text(encoding="utf-8").rstrip())
    except Exception, KeyboardInterrupt:
        api.finish_run(run["id"], "failed")
        raise
    api.finish_run(run["id"], "succeeded" if result.returncode == 0 else "failed")
    return exit_code(result.returncode)


def generate_goal_draft(message: str) -> GoalDraft:
    with TemporaryDirectory(prefix="harness-goal-") as directory:
        schema = Path(directory) / "draft.json"
        schema.write_text(json.dumps(GOAL_DRAFT.json_schema()), encoding="utf-8")
        result = _run_codex(message, DRAFT_INSTRUCTIONS, schema=schema)
    result.check_returncode()
    return GOAL_DRAFT.validate_json(result.stdout)
