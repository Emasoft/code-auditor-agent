"""Tiny Click CLI fixture for the cli_python_click discoverer tests."""

import click


@click.group()
def cli():
    """Top-level CLI entry point for the mycli command group."""
    pass


@cli.command()
def users_list():
    """List all users currently registered with the system."""
    click.echo("users list")


@click.option("--email", required=True, help="Email address of the new user.")
@click.option("--name", required=True, help="Display name of the new user.")
@cli.command(name="create-user")
def create_user(name: str, email: str) -> None:
    """Create a new user with the given name and email address."""
    click.echo(f"created user {name} <{email}>")


if __name__ == "__main__":
    cli()
