"""Agent CLI entrypoint.

Usage:
    python -m quarry.agent run-once
    python -m quarry.agent seed
"""

import click

from quarry.store.db import get_db


@click.group()
def cli():
    """Quarry agent commands."""
    pass


@cli.command()
def run_once():
    """Run a single crawl cycle."""
    import logging

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )

    from quarry.agent.scheduler import run_once as do_run

    db = get_db()
    summary = do_run(db)
    click.echo(f"Crawl complete: {summary}")


@cli.command()
def seed():
    """Load seed data into the database."""
    import logging

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )

    from quarry.agent.tools import seed as do_seed

    db = get_db()
    do_seed(db)
    click.echo("Seed data loaded.")


if __name__ == "__main__":
    cli()
