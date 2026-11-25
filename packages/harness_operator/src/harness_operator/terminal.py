import json
import sys

import click

POSITIVE_INTEGER = click.IntRange(1, 2**63 - 1)


def read_message(message: str | None, prompt: str) -> str:
    if message is None:
        if sys.stdin.isatty():
            click.echo(prompt, err=True, nl=False)
            message = sys.stdin.readline()
        else:
            message = sys.stdin.read()
    if not message.strip():
        raise click.UsageError("Provide a message as an argument or on standard input.")
    return message


def print_record(record: object) -> None:
    click.echo(json.dumps(record, ensure_ascii=False, indent=2))
