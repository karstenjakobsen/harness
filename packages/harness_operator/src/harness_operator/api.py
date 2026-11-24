import json
import re
from collections.abc import Callable
from typing import get_args

import click
import httpx
from click.core import ParameterSource
from pydantic import TypeAdapter, ValidationError

from harness_api import AssessmentType, GoalAPI, GoalDuration, GoalSummary

DEFAULT_API_URL = "http://127.0.0.1:8000"
GOAL_LIST = TypeAdapter(list[GoalSummary])


@click.group()
@click.option(
    "--url",
    envvar="HARNESS_API_URL",
    default=DEFAULT_API_URL,
    show_default=True,
    show_envvar=True,
    help="HTTP base URL for 'goals list'.",
)
@click.pass_context
def api(ctx: click.Context, url: str) -> None:
    """Access the Harness API directly."""
    ctx.obj = url


def _http_base_url(url: str) -> str:
    try:
        base_url = httpx.URL(url)
    except httpx.InvalidURL as error:
        raise click.BadParameter("Invalid API URL.", param_hint="--url") from error
    if (
        base_url.scheme not in {"http", "https"}
        or not base_url.host
        or (base_url.port is not None and not 1 <= base_url.port <= 65535)
        or base_url.userinfo
        or base_url.query
        or base_url.fragment
    ):
        raise click.BadParameter(
            "Use an HTTP or HTTPS address with an optional base path.",
            param_hint="--url",
        )
    return str(base_url.copy_with(query=None, fragment=None)).rstrip("/")


@api.group()
@click.pass_context
def goals(ctx: click.Context) -> None:
    """Manage workspace goals directly, or list goals from the HTTP server."""
    if (
        ctx.invoked_subcommand != "list"
        and ctx.parent is not None
        and ctx.parent.get_parameter_source("url") == ParameterSource.COMMANDLINE
    ):
        raise click.UsageError(
            "--url applies to 'goals list'. This command uses the workspace database."
        )


@goals.command("list")
@click.option(
    "--json", "as_json", is_flag=True, help="Print the full API response as JSON."
)
@click.pass_obj
def list_goals(api_url: str, as_json: bool) -> None:
    """List goals from the Harness API."""
    api_url = _http_base_url(api_url)
    try:
        response = httpx.get(f"{api_url}/goals", timeout=5.0, trust_env=False)
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise click.ClickException(
            f"The Harness API returned HTTP {error.response.status_code}."
        ) from error
    except httpx.RequestError as error:
        raise click.ClickException(
            f"Could not reach the Harness API at {api_url}. Start it with `make api`."
        ) from error

    body = response.content
    try:
        saved_goals = GOAL_LIST.validate_json(body)
    except ValidationError as error:
        raise click.ClickException(
            "The Harness API returned an invalid goal list."
        ) from error

    if as_json:
        click.echo(body, nl=not body.endswith(b"\n"))
        return

    if not saved_goals:
        click.echo("No saved goals.")
        return
    for goal in saved_goals:
        operator = goal["operator"]
        assignment = f" (assigned to {operator})" if operator else ""
        line = f"#{goal['id']} [{goal['status']}] {goal['title'] or '(untitled)'}{assignment}"
        click.echo(re.sub(r"[\x00-\x1f\x7f-\x9f]+", " ", line))


GOAL_ID = click.IntRange(-(2**63), 2**63 - 1)
POSITIVE_INTEGER = click.IntRange(1, 2**63 - 1)


def definition_options(command: Callable) -> Callable:
    """Attach the editable revision fields to both owner commands."""
    options = [
        click.option("--desired-outcome", help="Result the owner wants."),
        click.option("--duration", type=click.Choice(get_args(GoalDuration.__value__))),
        click.option("--duration-days", type=POSITIVE_INTEGER),
        click.option(
            "--assessment-type", type=click.Choice(get_args(AssessmentType.__value__))
        ),
        click.option("--success-criteria", help="What counts as success."),
        click.option("--measurement-plan", help="How success will be verified."),
    ]
    for option in reversed(options):
        command = option(command)
    return command


def _print_record(record: object) -> None:
    click.echo(json.dumps(record, ensure_ascii=False, indent=2))


@goals.command()
@click.option("--title", required=True, help="Goal title.")
@click.option("--parent", "parent_goal_id", type=GOAL_ID)
@definition_options
def create(title: str, parent_goal_id: int | None, **fields) -> None:
    """Create an active goal in the workspace database."""
    _print_record(
        GoalAPI().create_goal(
            title, status="active", parent_goal_id=parent_goal_id, **fields
        )
    )


@goals.command()
@click.argument("goal_id", type=GOAL_ID)
@click.option("--title", help="New goal title.")
@definition_options
def revise(goal_id: int, **fields) -> None:
    """Revise the supplied fields and return the current goal."""
    changes = {key: value for key, value in fields.items() if value is not None}
    if not changes:
        raise click.UsageError("Supply at least one field to revise.")
    _print_record(GoalAPI().update_goal(goal_id, **changes))


@goals.command()
@click.argument("goal_id", type=GOAL_ID)
@click.option("--revision", type=POSITIVE_INTEGER, required=True)
@click.option("--confirmation", help="The owner's confirmation of completion.")
@click.option(
    "--reference", help="An external evidence reference supplied by the owner."
)
def complete(
    goal_id: int, revision: int, confirmation: str | None, reference: str | None
) -> None:
    """Complete the verified revision and return its evidence record."""
    _print_record(
        GoalAPI().complete_goal(
            goal_id, revision, confirmation=confirmation, reference=reference
        )
    )


@goals.command()
@click.argument("goal_id", type=GOAL_ID)
@click.option("--tree", is_flag=True, help="Include descendants and current evidence.")
@click.option(
    "--history", is_flag=True, help="List this goal's revisions and their evidence."
)
def show(goal_id: int, tree: bool, history: bool) -> None:
    """Read a saved goal."""
    if tree and history:
        raise click.UsageError("Choose either --tree or --history.")
    api = GoalAPI()
    if tree:
        _print_record(api.get_goal_tree(goal_id))
    elif history:
        _print_record(api.get_goal_history(goal_id))
    else:
        _print_record(api.get_goal(goal_id))
