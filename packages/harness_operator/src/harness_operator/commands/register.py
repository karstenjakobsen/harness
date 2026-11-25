import click

from harness_api import OperatorAPI

from ..codex import register_codex
from ..terminal import POSITIVE_INTEGER, print_record


@click.command()
@click.argument("name", required=False)
@click.option(
    "--user",
    "owner_user_id",
    type=POSITIVE_INTEGER,
    help="Workspace owner ID. Defaults to admin.",
)
@click.option("--mission", help="What the operator is responsible for.")
def register(name: str | None, owner_user_id: int | None, mission: str | None) -> None:
    """Register a named workspace operator. With no arguments, sign in to Codex."""
    if name is None:
        if owner_user_id is not None or mission is not None:
            raise click.UsageError(
                "Supply the operator NAME with registration options."
            )
        click.get_current_context().exit(register_codex())
    print_record(
        OperatorAPI().register_operator(
            name,
            owner_user_id,
            mission=mission,
        )
    )
