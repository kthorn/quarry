import click

from quarry.config import settings
from quarry.store.db import init_db


@click.group()
def cli():
    """Database management commands."""
    pass


@cli.command()
def init():
    """Initialize the database with schema."""
    init_db(settings.db_path)
    click.echo(f"Database initialized at {settings.db_path}")


if __name__ == "__main__":
    cli()
