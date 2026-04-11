"""Digest CLI entrypoint.

Usage:
    python -m quarry.digest              # Build and write digest file
    python -m quarry.digest --mark-seen  # Also mark included postings as seen
"""

import click

from quarry.store.db import get_db


@click.command()
@click.option(
    "--mark-seen", is_flag=True, default=False, help="Mark included postings as seen"
)
@click.option("--limit", default=None, type=int, help="Max postings to include")
@click.option("--output", "-o", default=None, help="Output file path")
def main(mark_seen: bool, limit: int | None, output: str | None):
    """Build and write a digest of new job postings."""
    import logging

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )

    from quarry.digest.digest import (
        build_digest,
        mark_digest_seen,
        write_digest,
    )

    db = get_db()
    entries = build_digest(db, limit=limit)

    if not entries:
        click.echo("No new postings found.")
        return

    path = write_digest(entries, output)
    click.echo(f"Digest written to {path} ({len(entries)} postings)")

    if mark_seen:
        mark_digest_seen(db, entries)
        click.echo(f"Marked {len(entries)} postings as seen.")


if __name__ == "__main__":
    main()
