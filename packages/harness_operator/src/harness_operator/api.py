import re

import click
import httpx
from pydantic import TypeAdapter, ValidationError

from harness_api import GoalSummary

DEFAULT_API_URL = "http://127.0.0.1:8000"
GOAL_LIST = TypeAdapter(list[GoalSummary])


@click.group()
@click.option(
    "--url",
    envvar="HARNESS_API_URL",
    default=DEFAULT_API_URL,
    show_default=True,
    show_envvar=True,
    help="Base URL for the Harness API.",
)
@click.pass_context
def api(ctx: click.Context, url: str) -> None:
    """Call the Harness HTTP API."""
    try:
        base_url = httpx.URL(url)
    except httpx.InvalidURL as error:
        raise click.BadParameter(
            "Invalid API URL.", ctx=ctx, param_hint="--url"
        ) from error
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
            ctx=ctx,
            param_hint="--url",
        )
    ctx.obj = str(base_url.copy_with(query=None, fragment=None)).rstrip("/")


@api.group()
def goals() -> None:
    """Work with saved goals over HTTP."""


@goals.command("list")
@click.pass_obj
def list_goals(api_url: str) -> None:
    """List goals from the Harness API."""
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

    try:
        saved_goals = GOAL_LIST.validate_json(response.content)
    except ValidationError as error:
        raise click.ClickException(
            "The Harness API returned an invalid goal list."
        ) from error

    if not saved_goals:
        click.echo("No saved goals.")
        return
    for goal in saved_goals:
        operator = goal["operator"]
        assignment = f" (assigned to {operator})" if operator else ""
        line = f"#{goal['id']} [{goal['status']}] {goal['title'] or '(untitled)'}{assignment}"
        click.echo(re.sub(r"[\x00-\x1f\x7f-\x9f]+", " ", line))
