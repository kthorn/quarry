"""Pipeline CLI entrypoint.

Usage:
    python -m quarry.pipeline embed-ideal   # Embed ideal role description from config
    python -m quarry.pipeline search        # Search and rank jobs by keywords/similarity
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

    embedding = set_ideal_embedding(db, desc, user_id=1)
    threshold = settings.similarity_threshold
    click.echo(
        f"Ideal role description embedded successfully.\n"
        f"  Description: {desc[:80]}...\n"
        f"  Embedding dim: {embedding.shape[0]}\n"
        f"  Similarity threshold: {threshold}"
    )


@cli.command()
@click.option("--ideal", default=None, help="Ideal role description to score against.")
@click.option(
    "--must-have-title",
    default=None,
    help="Comma-separated keywords; ANY match in title passes.",
)
@click.option(
    "--must-have-description",
    default=None,
    help="Comma-separated keywords; ANY match in description passes.",
)
@click.option("--limit", default=20, help="Maximum number of results.")
@click.option("--min-score", default=0.0, type=float, help="Minimum similarity score.")
@click.option("--status", default=None, help="Filter by posting status.")
def search(ideal, must_have_title, must_have_description, limit, min_score, status):
    """Search and rank jobs by keywords and/or embedding similarity.

    At least one of --ideal, --must-have-title, or --must-have-description is required.

    Examples:
        python -m quarry.pipeline search --ideal "senior python backend engineer"
        python -m quarry.pipeline search --must-have-title "senior,lead"
        python -m quarry.pipeline search --must-have-description "python,aws"
        python -m quarry.pipeline search --must-have-title "senior" --ideal "python backend"
    """
    if not ideal and not must_have_title and not must_have_description:
        click.echo(
            "Error: at least one of --ideal, --must-have-title, "
            "or --must-have-description is required."
        )
        raise SystemExit(1)

    db = get_db()
    postings = db.get_postings_for_search(status=status)

    if not postings:
        click.echo("No postings with embeddings found in the database.")
        return

    title_keywords = (
        [w.strip() for w in must_have_title.split(",") if w.strip()]
        if must_have_title
        else None
    )
    desc_keywords = (
        [w.strip() for w in must_have_description.split(",") if w.strip()]
        if must_have_description
        else None
    )

    from quarry.pipeline.search import (
        filter_by_keywords,
        format_results,
        score_postings,
    )

    if title_keywords or desc_keywords:
        click.echo(f"Filtering: {len(postings)} postings before keyword filter...")
        filtered = filter_by_keywords(postings, title_keywords, desc_keywords)
        click.echo(f"Matched: {len(filtered)} postings after keyword filter.")
    else:
        filtered = [(p, c, [], []) for p, c in postings]

    if not filtered:
        click.echo("No postings matched the keyword filters.")
        return

    has_score = ideal is not None

    if has_score:
        from quarry.pipeline.embedder import embed_text, get_embedding_dim

        click.echo(f"Embedding ideal role: {ideal[:60]}...")
        ideal_embedding = embed_text(ideal)
        dim = get_embedding_dim()
        results = score_postings(filtered, ideal_embedding, dim)
    else:
        results = [
            {
                "title": p.title,
                "company": cn,
                "score": 0.0,
                "matched_title": mt,
                "matched_desc": md,
            }
            for p, cn, mt, md in filtered
        ]

    output = format_results(
        results,
        has_score=has_score,
        has_title_keywords=title_keywords is not None,
        has_desc_keywords=desc_keywords is not None,
        limit=limit,
        min_score=min_score,
    )
    click.echo(output)


if __name__ == "__main__":
    cli()
