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
@click.option(
    "--definition-grant",
    type=POSITIVE_INTEGER,
    help="Bind this session to top-level creation, subgoal creation or revision.",
)
@click.option(
    "--work-grant", type=POSITIVE_INTEGER, help="Delegate worker tasks for one goal."
)
def ask(
    work_grant: int | None,
    message: str | None,
    trace_file: Path | None,
    completion_grant: int | None,
    definition_grant: int | None,
) -> None:
    """Review goals with Codex."""
    if sum(g is not None for g in (completion_grant, definition_grant, work_grant)) > 1:
        raise click.UsageError("Choose one grant for this session.")
    click.get_current_context().exit(
        ask_codex(
            read_message(message, "Ask operator: "),
            trace_file,
            completion_grant_id=completion_grant,
            definition_grant_id=definition_grant,
            work_grant_id=work_grant,
        )
    )
