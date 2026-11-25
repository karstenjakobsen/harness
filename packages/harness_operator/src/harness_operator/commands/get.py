import click

from harness_api import OperatorAPI

from ..terminal import POSITIVE_INTEGER, print_record


@click.command("get")
@click.argument("operator_id", type=POSITIVE_INTEGER)
def get_operator(operator_id: int) -> None:
    """Get a registered workspace operator by ID."""
    print_record(OperatorAPI().get_operator(operator_id))
