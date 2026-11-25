import click

from harness_api import OperatorAPI

from ..terminal import print_record


@click.command("list")
@click.option("--user", "owner_user_id", help="Show only operators owned by this user.")
def list_operators(owner_user_id: str | None) -> None:
    """List registered workspace operators."""
    print_record(OperatorAPI().list_operators(owner_user_id))
