import sys

import click

from harness_api import (
    AccountConflictError,
    AccountNotFoundError,
    AccountValidationError,
    GoalConflictError,
    GoalNotFoundError,
    GoalValidationError,
    RunNotFoundError,
    SkillCatalogError,
    WorkAuthorizationError,
    WorkConflictError,
    WorkNotFoundError,
    WorkspaceStorageError,
    WorkValidationError,
)

from .codex import ask_codex as ask_codex
from .codex import register_codex as register_codex
from .commands.ask import ask
from .commands.get import get_operator
from .commands.goal import create_goal as create_goal
from .commands.goal import goal
from .commands.list import list_operators
from .commands.register import register
from .commands.run import run
from .commands.unregister import unregister
from .commands.user import user
from .commands.work import work
from .worker import WorkerLaunchError


@click.group(
    commands=[
        ask,
        get_operator,
        goal,
        list_operators,
        register,
        run,
        unregister,
        user,
        work,
    ]
)
def cli() -> None:
    """Ask Codex about goals and manage the current workspace."""


def main() -> int:
    try:
        return cli.main(standalone_mode=False) or 0
    except click.ClickException as error:
        error.show()
        return error.exit_code
    except (
        AccountConflictError,
        AccountNotFoundError,
        AccountValidationError,
        GoalConflictError,
        GoalNotFoundError,
        GoalValidationError,
        RunNotFoundError,
        SkillCatalogError,
        WorkspaceStorageError,
        WorkConflictError,
        WorkNotFoundError,
        WorkAuthorizationError,
        WorkValidationError,
        WorkerLaunchError,
    ) as error:
        click.echo(f"operator: {error}", err=True)
        return 1
    except OSError as error:
        if isinstance(error, FileNotFoundError) and error.filename == "codex":
            click.echo(
                "operator: Install the Codex CLI and add 'codex' to PATH.", err=True
            )
            return 127
        print(f"operator: {error}", file=sys.stderr)
        return 1
    except click.Abort:
        return 130
