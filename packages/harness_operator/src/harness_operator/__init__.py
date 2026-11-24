import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TextIO

import click
from pydantic import BaseModel, ConfigDict, ValidationError

from harness_api import (
    AssessmentType,
    GoalAPI,
    GoalDuration,
    GoalNotFoundError,
    GoalStorageError,
    GoalValidationError,
)

from .api import api as api_command

OPERATOR_INSTRUCTIONS = """\
You are the user's goal operator. Treat goals as flexible guidelines.
Read relevant workspace files when helpful and suggest a small next step.
Use the harness_mcp list_goals tool to find saved goal IDs. For questions about a
plan, its requirements, status, or evidence, call get_goal_tree with the goal ID.
Use the returned records to answer. List each goal on its own line with its status
and the relevant timing or evidence. Draft, active, and paused goals are open.
Attribute owner confirmations and owner-supplied references to the owner.
If the tool fails, say that you could not retrieve the goals.
Keep this turn advisory. Describe goal changes as proposals.
"""

DRAFT_INSTRUCTIONS = """\
Draft a goal from the user's request. Keep the definition light and provisional.
Decide duration and assessment type independently.
Duration is one_time if the user wants a result verified once, or standing if they want it maintained.
Assessment is objective for a checkable result, judgment for human judgment, or mixed if both matter.
Describe the desired outcome, what would count as success, and how to assess it when clear.
Leave uncertain fields null. Ask one focused question if the goal needs clarification.
Preserve the user's intent and leave review timing unspecified unless the user supplied it.
Return a draft definition only. Do not carry out the goal or run checks.
"""


class GoalDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    desired_outcome: str | None
    duration: GoalDuration | None
    assessment_type: AssessmentType | None
    success_criteria: str | None
    measurement_plan: str | None
    clarification: str | None


def _exit_code(returncode: int) -> int:
    return returncode if returncode >= 0 else 128 - returncode


def register_codex() -> int:
    result = subprocess.run(["codex", "login", "--device-auth"], check=False)
    return _exit_code(result.returncode)


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
        return _exit_code(_run_codex(message, OPERATOR_INSTRUCTIONS).returncode)
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
            click.echo(reply_path.read_text(encoding="utf-8").rstrip())
    return _exit_code(result.returncode)


def create_goal(message: str) -> int:
    with TemporaryDirectory(prefix="harness-goal-") as directory:
        schema = Path(directory) / "draft.json"
        schema.write_text(json.dumps(GoalDraft.model_json_schema()), encoding="utf-8")
        result = _run_codex(message, DRAFT_INSTRUCTIONS, schema=schema)
    if result.returncode:
        return _exit_code(result.returncode)

    try:
        draft = GoalDraft.model_validate_json(result.stdout)
    except ValidationError:
        print("operator: Codex returned an invalid goal draft.", file=sys.stderr)
        return 1

    clarification = (draft.clarification or "").strip() or None
    if clarification is None and draft.duration is None:
        clarification = (
            "Once I verify this, are we done, or do you want me to keep checking?"
        )
    if clarification is None and draft.assessment_type is None:
        clarification = "What would show that this goal is being met?"

    try:
        goal = GoalAPI().create_goal(
            draft.title,
            desired_outcome=draft.desired_outcome,
            duration=draft.duration,
            assessment_type=draft.assessment_type,
            success_criteria=draft.success_criteria,
            measurement_plan=draft.measurement_plan,
            original_message=message,
            clarification=clarification,
        )
    except (GoalValidationError, GoalStorageError) as error:
        print(f"operator: Could not save the draft. {error}", file=sys.stderr)
        return 1

    print(f"Saved draft goal #{goal['id']} — {goal['title']}")
    duration = {"one_time": "One-time", "standing": "Standing"}.get(
        draft.duration, "Duration open"
    )
    assessment = {
        "objective": "Objective check",
        "judgment": "Human judgment",
        "mixed": "Objective check and human judgment",
    }.get(draft.assessment_type, "Assessment open")
    print(f"{duration} · {assessment}")
    if clarification:
        print(clarification)
    return 0


def _read_message(message: str | None, prompt: str) -> str:
    if message is None:
        if sys.stdin.isatty():
            click.echo(prompt, err=True, nl=False)
            message = sys.stdin.readline()
        else:
            message = sys.stdin.read()
    if not message.strip():
        raise click.UsageError("Provide a message as an argument or on standard input.")
    return message


@click.group()
def cli() -> None:
    """Talk to a goal operator and access the Harness API."""


cli.add_command(api_command)


@cli.command()
@click.argument("message", required=False)
@click.option(
    "--trace-file",
    type=click.Path(path_type=Path),
    help="Save Codex JSON events to a new file.",
)
def ask(message: str | None, trace_file: Path | None) -> None:
    """Ask Codex for advice on a goal."""
    click.get_current_context().exit(
        ask_codex(_read_message(message, "Ask operator: "), trace_file)
    )


@cli.command()
def register() -> None:
    """Sign in to Codex using a device code."""
    click.get_current_context().exit(register_codex())


@cli.group()
def goal() -> None:
    """Manage saved goals with Codex."""


@goal.command()
@click.argument("message", required=False)
def create(message: str | None) -> None:
    """Ask Codex to draft a goal from a message and save it."""
    click.get_current_context().exit(create_goal(_read_message(message, "New goal: ")))


def main() -> int:
    try:
        return cli.main(standalone_mode=False) or 0
    except click.ClickException as error:
        error.show()
        return error.exit_code
    except (GoalNotFoundError, GoalValidationError, GoalStorageError) as error:
        click.echo(f"operator: {error}", err=True)
        return 1
    except OSError as error:
        if isinstance(error, FileNotFoundError) and error.filename == "codex":
            click.echo(
                "operator: Install the Codex CLI and add 'codex' to PATH.", err=True
            )
            return 127
        print(f"operator: {error}", file=sys.stderr)
        return 1
    except click.Abort:
        return 130
