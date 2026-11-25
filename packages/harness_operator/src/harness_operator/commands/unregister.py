import click

from harness_api import OperatorAPI

from ..terminal import POSITIVE_INTEGER, print_record


@click.command()
@click.argument("operator_id", type=POSITIVE_INTEGER)
def unregister(operator_id: int) -> None:
    """Soft-delete a workspace operator and release its goal assignments."""
    print_record(OperatorAPI().unregister_operator(operator_id))
