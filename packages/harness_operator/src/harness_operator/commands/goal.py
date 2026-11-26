import subprocess
import sys
from collections.abc import Callable
from typing import get_args

import click
from pydantic import ValidationError

from harness_api import (
    AssessmentType,
    GoalAPI,
    GoalDuration,
    GoalStorageError,
    GoalValidationError,
)

from ..codex import exit_code, generate_goal_draft
from ..terminal import POSITIVE_INTEGER, print_record, read_message


def create_goal(message: str) -> int:
    try:
        draft = generate_goal_draft(message)
    except subprocess.CalledProcessError as error:
        return exit_code(error.returncode)
    except ValidationError:
        print("operator: Codex returned an invalid goal draft.", file=sys.stderr)
        return 1

    try:
        goal, clarification = GoalAPI().save_goal_draft(message, **draft)
    except (GoalValidationError, GoalStorageError) as error:
        print(f"operator: Could not save the draft. {error}", file=sys.stderr)
        return 1

    print(f"Saved draft goal #{goal['id']} — {goal['title']}")
    duration = {"one_time": "One-time", "standing": "Standing"}.get(
        goal["duration"], "Duration open"
    )
    assessment = {
        "objective": "Objective check",
        "judgment": "Human judgment",
        "mixed": "Objective check and human judgment",
    }.get(goal["assessment_type"], "Assessment open")
    print(f"{duration} · {assessment}")
    if clarification:
        print(clarification)
    return 0


@click.group()
def goal() -> None:
    """Manage goals in the current workspace."""


def definition_options(command: Callable) -> Callable:
    """Attach the editable revision fields to both owner commands."""
    options = [
        click.option("--desired-outcome", help="Result the owner wants."),
        click.option("--duration", type=click.Choice(get_args(GoalDuration.__value__))),
        click.option("--duration-days", type=POSITIVE_INTEGER),
        click.option(
            "--target-distinct-dates",
            type=POSITIVE_INTEGER,
            help="Count distinct dates confirmed by the owner.",
        ),
        click.option(
            "--window-start",
            help="First calendar date of the duration in days (YYYY-MM-DD).",
        ),
        click.option(
            "--assessment-type", type=click.Choice(get_args(AssessmentType.__value__))
        ),
        click.option("--success-criteria", help="What counts as success."),
        click.option("--measurement-plan", help="How success will be verified."),
    ]
    for option in reversed(options):
        command = option(command)
    return command


@goal.command("list")
def list_workspace_goals() -> None:
    """List goals from the current workspace as JSON."""
    print_record(GoalAPI().list_goals())


@goal.command()
@click.argument("message", required=False)
@click.option("--title", help="Save an active workspace goal with this exact title.")
@click.option("--parent", "parent_goal_id", type=POSITIVE_INTEGER)
@definition_options
def create(
    message: str | None, title: str | None, parent_goal_id: int | None, **fields
) -> None:
    """Draft a workspace goal from a message, or create an active one with --title."""
    if title is not None:
        if message is not None:
            raise click.UsageError("Choose a message or an explicit --title.")
        print_record(
            GoalAPI().create_goal(
                title, status="active", parent_goal_id=parent_goal_id, **fields
            )
        )
    else:
        if parent_goal_id is not None or any(
            value is not None for value in fields.values()
        ):
            raise click.UsageError("Supply --title with explicit goal fields.")
        click.get_current_context().exit(
            create_goal(read_message(message, "New goal: "))
        )


@goal.command()
@click.argument("goal_id", type=POSITIVE_INTEGER)
@click.option("--title", help="New goal title.")
@definition_options
def revise(goal_id: int, **fields) -> None:
    """Revise the supplied fields and return the current goal."""
    changes = {key: value for key, value in fields.items() if value is not None}
    if not changes:
        raise click.UsageError("Supply at least one field to revise.")
    print_record(GoalAPI().update_goal(goal_id, **changes))


@goal.command()
@click.argument("goal_id", type=POSITIVE_INTEGER)
@click.option("--revision", type=POSITIVE_INTEGER, required=True)
@click.option("--confirmation", help="The owner's confirmation of completion.")
@click.option(
    "--reference", help="An external evidence reference supplied by the owner."
)
@click.option(
    "--evidence-id",
    "evidence_ids",
    type=POSITIVE_INTEGER,
    multiple=True,
    help="Cite a saved evidence ID. Repeat for additional records.",
)
def complete(
    goal_id: int,
    revision: int,
    confirmation: str | None,
    reference: str | None,
    evidence_ids: tuple[int, ...],
) -> None:
    """Complete the verified revision and return its evidence record."""
    print_record(
        GoalAPI().complete_goal(
            goal_id,
            revision,
            confirmation=confirmation,
            reference=reference,
            evidence_ids=evidence_ids,
        )
    )


@goal.command()
@click.argument("goal_id", type=POSITIVE_INTEGER)
@click.argument("operator_id", type=POSITIVE_INTEGER)
def grant_completion(goal_id: int, operator_id: int) -> None:
    """Delegate completion of one subgoal and return the new grant."""
    print_record(GoalAPI().grant_completion(goal_id, operator_id))


@goal.command()
@click.argument("grant_id", type=POSITIVE_INTEGER)
def withdraw_completion(grant_id: int) -> None:
    """Withdraw completion authority for a specific grant."""
    print_record(GoalAPI().withdraw_completion(grant_id))


@goal.command()
@click.argument("operator_id", type=POSITIVE_INTEGER)
def grant_create(operator_id: int) -> None:
    """Grant creation authority and return the new grant.

    This operator may create top-level goals in this workspace until you withdraw the grant.
    """
    print_record(GoalAPI().grant_definition("create_goal", operator_id))


@goal.command()
@click.argument("parent_id", type=POSITIVE_INTEGER)
@click.argument("operator_id", type=POSITIVE_INTEGER)
def grant_subgoals(parent_id: int, operator_id: int) -> None:
    """Grant creation of direct draft children under this parent."""
    print_record(
        GoalAPI().grant_definition("create_subgoal", operator_id, goal_id=parent_id)
    )


@goal.command()
@click.argument("goal_id", type=POSITIVE_INTEGER)
@click.argument("operator_id", type=POSITIVE_INTEGER)
def grant_revision(goal_id: int, operator_id: int) -> None:
    """Grant revision authority for the specified goal and return the new grant."""
    print_record(
        GoalAPI().grant_definition("revise_goal", operator_id, goal_id=goal_id)
    )


@goal.command()
@click.argument("grant_id", type=POSITIVE_INTEGER)
def withdraw_definition_grant(grant_id: int) -> None:
    """Withdraw a creation or revision grant and invalidate sessions bound to it."""
    print_record(GoalAPI().withdraw_definition_grant(grant_id))


@goal.command()
@click.argument("goal_id", type=POSITIVE_INTEGER)
@click.option(
    "--tree",
    is_flag=True,
    help="Include descendants and their current completion decisions.",
)
@click.option(
    "--history", is_flag=True, help="List this goal's revisions and their evidence."
)
def show(goal_id: int, tree: bool, history: bool) -> None:
    """Read a saved goal."""
    if tree and history:
        raise click.UsageError("Choose either --tree or --history.")
    api = GoalAPI()
    if tree:
        print_record(api.get_goal_tree(goal_id))
    elif history:
        print_record(api.get_goal_history(goal_id))
    else:
        print_record(api.get_goal(goal_id))


@goal.command()
@click.argument("goal_id", type=POSITIVE_INTEGER)
def history(goal_id: int) -> None:
    """Read the goal timeline and discover related operator runs."""
    print_record(GoalAPI().get_goal_activity(goal_id))


@goal.command()
@click.argument("goal_id", type=POSITIVE_INTEGER)
@click.option("--confirmation", help="What the owner confirms.")
@click.option("--reference", help="A reference supplied by the owner.")
@click.option(
    "--reported-date",
    help="The date the report concerns, through today in UTC (YYYY-MM-DD).",
)
@click.option(
    "--retry-key", required=True, help="Reuse this key when retrying this submission."
)
def observe(goal_id: int, **report) -> None:
    """Record a report independently of completion."""
    print_record(GoalAPI().record_observation(goal_id, **report))


@goal.command()
@click.argument("goal_id", type=POSITIVE_INTEGER)
@click.option(
    "--revision",
    type=POSITIVE_INTEGER,
    help="Assess this revision using the evidence available now.",
)
def progress(goal_id: int, revision: int | None) -> None:
    """Show the assessment, all evidence considered, and the dates that counted."""
    print_record(GoalAPI().get_goal_progress(goal_id, revision))


@goal.command()
@click.argument("goal_id", type=POSITIVE_INTEGER)
@click.argument("operator_id", type=POSITIVE_INTEGER)
def grant_work(goal_id: int, operator_id: int) -> None:
    """Authorize one operator to delegate work on this goal."""
    print_record(GoalAPI().grant_work(goal_id, operator_id))


@goal.command()
@click.argument("grant_id", type=POSITIVE_INTEGER)
def withdraw_work(grant_id: int) -> None:
    """Close this grant and its worker access."""
    print_record(GoalAPI().withdraw_work(grant_id))
