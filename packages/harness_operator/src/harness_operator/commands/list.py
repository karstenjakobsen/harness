import click

from harness_api import OperatorAPI

from ..terminal import POSITIVE_INTEGER, print_record


@click.command("list")
@click.option(
    "--user",
    "owner_user_id",
    type=POSITIVE_INTEGER,
    help="Show only operators owned by this user.",
)
def list_operators(owner_user_id: int | None) -> None:
    """List registered workspace operators."""
    print_record(OperatorAPI().list_operators(owner_user_id))
