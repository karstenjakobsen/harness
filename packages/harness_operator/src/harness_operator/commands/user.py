import click

from harness_api import UserAPI

from ..terminal import POSITIVE_INTEGER, print_record


@click.group()
def user() -> None:
    """Manage users in the current workspace."""


@user.command("create")
@click.argument("username")
@click.option("--name", "display_name", help="Display name. Defaults to the username.")
def create_user(username: str, display_name: str | None) -> None:
    """Create a workspace user and return its generated ID."""
    print_record(UserAPI().create_user(username, display_name))


@user.command("get")
@click.argument("user_id", type=POSITIVE_INTEGER)
def get_user(user_id: int) -> None:
    """Get a workspace user by ID."""
    print_record(UserAPI().get_user(user_id))


@user.command("list")
def list_users() -> None:
    """List current workspace users."""
    print_record(UserAPI().list_users())


@user.command("update")
@click.argument("user_id", type=POSITIVE_INTEGER)
@click.option("--name", "display_name", required=True, help="New display name.")
def update_user(user_id: int, display_name: str) -> None:
    """Update a workspace user's display name."""
    print_record(UserAPI().update_user(user_id, display_name))


@user.command("delete")
@click.argument("user_id", type=POSITIVE_INTEGER)
def delete_user(user_id: int) -> None:
    """Soft-delete a user after all their operators have been unregistered."""
    print_record(UserAPI().delete_user(user_id))
