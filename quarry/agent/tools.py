"""Agent tools: seed data loading and strategy utilities."""

import logging
import sys
from pathlib import Path

import click
import yaml

from quarry.config import settings
from quarry.models import Company, SearchQuery
from quarry.store.db import Database, init_db

log = logging.getLogger(__name__)


def load_seed_data(
    seed_path: str | None = None,
) -> tuple[list[Company], list[SearchQuery]]:
    """Load companies and search queries from a YAML seed file.

    Supports both dict format (with 'companies' and 'search_queries' keys)
    and legacy flat list format (list of company dicts only).

    Args:
        seed_path: Path to seed_data.yaml. Defaults to config seed_file.

    Returns:
        Tuple of (companies, search_queries) parsed from the YAML file.

    Raises:
        FileNotFoundError: If seed file does not exist.
    """
    path = Path(seed_path or settings.seed_file)
    if not path.exists():
        print(f"Error: seed file not found: {path}", file=sys.stderr)
        sys.exit(1)

    with open(path) as f:
        data = yaml.safe_load(f)

    if not data:
        print("Error: seed file is empty", file=sys.stderr)
        sys.exit(1)

    if isinstance(data, list):
        companies_data = data
        queries_data = []
    else:
        companies_data = data.get("companies", [])
        queries_data = data.get("search_queries", [])

    companies = []
    for c in companies_data:
        companies.append(
            Company(
                name=c["name"],
                domain=c.get("domain"),
                careers_url=c.get("careers_url"),
                ats_type=c.get("ats_type", "unknown"),
                ats_slug=c.get("ats_slug"),
                active=c.get("active", True),
                crawl_priority=c.get("crawl_priority", 5),
                notes=c.get("notes"),
                added_by="seed",
                added_reason=c.get("added_reason"),
            )
        )

    queries = []
    for q in queries_data:
        queries.append(
            SearchQuery(
                query_text=q["query_text"],
                site=q.get("site"),
                active=q.get("active", True),
                added_by="seed",
                added_reason=q.get("added_reason"),
            )
        )

    return companies, queries


def seed(db: Database | None = None, seed_file: str | None = None) -> tuple[int, int]:
    """Load seed data into the database.

    Idempotent: skips companies/queries that already exist (by name/query_text).

    Args:
        db: Database instance (loads from config if None)
        seed_file: Path to YAML file (uses config if None)

    Returns:
        Tuple of (total_inserted, total_skipped)
    """
    if db is None:
        db = Database(settings.db_path)

    companies, queries = load_seed_data(seed_file)

    existing_companies = {
        c.name.lower() for c in db.get_all_companies(active_only=False)
    }
    inserted = 0
    skipped = 0

    for company in companies:
        if company.name.lower() in existing_companies:
            log.info("Skipping existing company: %s", company.name)
            skipped += 1
            continue
        db.insert_company(company)
        existing_companies.add(company.name.lower())
        log.info("Seeded company: %s", company.name)
        inserted += 1

    existing_queries = {q.query_text for q in db.get_active_search_queries()}
    for query in queries:
        if query.query_text in existing_queries:
            log.info("Skipping existing query: %s", query.query_text)
            skipped += 1
            continue
        db.insert_search_query(query)
        existing_queries.add(query.query_text)
        log.info("Seeded query: %s", query.query_text)
        inserted += 1

    log.info("Seed complete: %d inserted, %d skipped", inserted, skipped)
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
    inserted, skipped = seed(db=db, seed_file=seed_file)
    click.echo(f"Seeded {inserted} entries, skipped {skipped}")


@cli.command(name="normalize-locations")
@click.option("--dry-run", is_flag=True, help="Report stats without making changes")
def normalize_locations_command(dry_run: bool):
    """Parse and normalize location data for all existing postings."""
    from quarry.models import JobPosting
    from quarry.pipeline.locations import parse_location

    db = init_db(settings.db_path)

    rows = db.execute(
        "SELECT * FROM job_postings WHERE location IS NOT NULL AND location != ''"
    )
    parsed_postings = [JobPosting(**dict(row)) for row in rows]
    click.echo(f"Found {len(parsed_postings)} postings with locations")

    locations_created = 0
    links_created = 0
    unresolvable = 0

    for posting in parsed_postings:
        parse_result = parse_location(posting.location)

        if parse_result.work_model and not posting.work_model:
            if not dry_run:
                db.execute(
                    "UPDATE job_postings SET work_model = ? WHERE id = ?",
                    (parse_result.work_model, posting.id),
                )

        for loc in parse_result.locations:
            if not dry_run:
                loc_id = db.get_or_create_location(loc)
                db.link_posting_location(posting.id or 0, loc_id)
            locations_created += 1
            if loc.resolution_status == "needs_review":
                unresolvable += 1
                click.echo(
                    f"  Needs review: {loc.raw_fragment} -> {loc.canonical_name}"
                )
            links_created += 1

    click.echo(f"Locations created: {locations_created}")
    click.echo(f"Links created: {links_created}")
    click.echo(f"Unresolvable fragments: {unresolvable}")
    if dry_run:
        click.echo("(dry run — no changes made)")


if __name__ == "__main__":
    cli()
