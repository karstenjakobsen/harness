import click

from harness_api import GoalAPI

from ..terminal import POSITIVE_INTEGER, print_record


@click.group()
def run() -> None:
    """Inspect operator runs in the current workspace."""


@run.command()
@click.argument("run_id", type=POSITIVE_INTEGER)
def show(run_id: int) -> None:
    """Read a saved run with its ordered tool calls."""
    print_record(GoalAPI().get_run(run_id))
