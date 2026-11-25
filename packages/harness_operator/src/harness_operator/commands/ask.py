from pathlib import Path

import click

from ..codex import ask_codex
from ..terminal import POSITIVE_INTEGER, read_message


@click.command()
@click.argument("message", required=False)
@click.option(
    "--trace-file",
    type=click.Path(path_type=Path),
    help="Save Codex JSON events to a new file.",
)
@click.option(
    "--completion-grant",
    type=POSITIVE_INTEGER,
    help="Bind this session to a particular subgoal completion grant.",
)
def ask(
    message: str | None, trace_file: Path | None, completion_grant: int | None
) -> None:
    """Review goals with Codex."""
    click.get_current_context().exit(
        ask_codex(
            read_message(message, "Ask operator: "),
            trace_file,
            completion_grant_id=completion_grant,
        )
    )
