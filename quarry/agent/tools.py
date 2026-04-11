import sys
from pathlib import Path

import click
import yaml

from quarry.config import settings
from quarry.models import Company
from quarry.store.db import Database, init_db


def seed(db: Database | None = None, seed_file: str | None = None) -> tuple[int, int]:
    """Load companies from seed_data.yaml into the database.

    Args:
        db: Database instance (loads from config if None)
        seed_file: Path to YAML file (uses config if None)

    Returns:
        Tuple of (inserted_count, skipped_count)
    """
    if db is None:
        db = Database(settings.db_path)

    seed_path = Path(seed_file or settings.seed_file)

    if not seed_path.exists():
        print(f"Error: seed file not found: {seed_path}", file=sys.stderr)
        sys.exit(1)

    with open(seed_path) as f:
        companies_data = yaml.safe_load(f)

    if not companies_data:
        print("Error: seed file is empty", file=sys.stderr)
        sys.exit(1)

    existing = {c.name for c in db.get_all_companies(active_only=False)}

    inserted = 0
    skipped = 0

    for entry in companies_data:
        name = entry.get("name")
        if not name:
            print(f"Warning: skipping entry with no name: {entry}", file=sys.stderr)
            skipped += 1
            continue

        if name in existing:
            skipped += 1
            continue

        company = Company(
            name=name,
            domain=entry.get("domain"),
            careers_url=entry.get("careers_url"),
            ats_type=entry.get("ats_type", "unknown"),
            ats_slug=entry.get("ats_slug"),
            active=entry.get("active", True),
            crawl_priority=entry.get("crawl_priority", 5),
            notes=entry.get("notes"),
            added_by="seed",
            added_reason=entry.get("added_reason"),
        )
        db.insert_company(company)
        existing.add(name)
        inserted += 1

    print(f"Seeded {inserted} companies, skipped {skipped}")
    return inserted, skipped


@click.group()
def cli():
    """Quarry agent tools."""
    pass


@cli.command(name="seed")
@click.option("--seed-file", default=None, help="Path to seed YAML file")
def seed_command(seed_file):
    """Seed the database with companies from YAML file."""
    db = init_db(settings.db_path)
    seed(db=db, seed_file=seed_file)


if __name__ == "__main__":
    cli()
