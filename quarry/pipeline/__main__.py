"""Pipeline CLI entrypoint.

Usage:
    python -m quarry.pipeline embed-ideal   # Embed ideal role description from config
"""

import click

from quarry.config import settings
from quarry.store.db import get_db


@click.group()
def cli():
    """Pipeline commands for embedding and filtering."""
    pass


@cli.command()
def embed_ideal():
    """Embed the ideal role description and store in DB."""
    db = get_db()
    desc = settings.ideal_role_description
    if not desc:
        click.echo("Error: ideal_role_description is empty in config.")
        raise SystemExit(1)

    from quarry.pipeline.embedder import set_ideal_embedding

    embedding = set_ideal_embedding(db, desc)
    threshold = settings.similarity_threshold
    click.echo(
        f"Ideal role description embedded successfully.\n"
        f"  Description: {desc[:80]}...\n"
        f"  Embedding dim: {embedding.shape[0]}\n"
        f"  Similarity threshold: {threshold}"
    )


if __name__ == "__main__":
    cli()
