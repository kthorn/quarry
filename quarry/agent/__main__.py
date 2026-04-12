"""Agent CLI entrypoint.

Usage:
    python -m quarry.agent run-once
    python -m quarry.agent seed
    python -m quarry.agent recompute-similarity
"""

import click

from quarry.store.db import get_db


def _configure_logging():
    import logging
    import os

    os.environ["TQDM_DISABLE"] = "1"
    os.environ["TRANSFORMERS_VERBOSITY"] = "error"
    logging.basicConfig(
        level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    for noisy in ("httpx", "httpcore", "transformers", "sentence_transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@click.group()
def cli():
    """Quarry agent commands."""
    pass


@cli.command()
def run_once():
    """Run a single crawl cycle."""
    _configure_logging()

    from quarry.agent.scheduler import run_once as do_run

    db = get_db()
    summary = do_run(db)
    click.echo(f"Crawl complete: {summary}")


@cli.command()
def seed():
    """Load seed data into the database."""
    _configure_logging()

    from quarry.agent.tools import seed as do_seed

    db = get_db()
    do_seed(db)
    click.echo("Seed data loaded.")


@cli.command(name="recompute-similarity")
def recompute_similarity():
    """Recompute all similarity scores against the current ideal role embedding."""
    _configure_logging()

    from quarry.agent.tools import recompute_similarity as do_recompute

    db = get_db()
    do_recompute(db)
    click.echo("Done.")


if __name__ == "__main__":
    cli()
