from pathlib import Path

import click

from ..codex import ask_codex
from ..terminal import read_message


@click.command()
@click.argument("message", required=False)
@click.option(
    "--trace-file",
    type=click.Path(path_type=Path),
    help="Save Codex JSON events to a new file.",
)
def ask(message: str | None, trace_file: Path | None) -> None:
    """Ask Codex for advice on a goal."""
    click.get_current_context().exit(
        ask_codex(read_message(message, "Ask operator: "), trace_file)
    )
