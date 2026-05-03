"""Agent tools: seed data loading and strategy utilities."""

import logging
import sys
from pathlib import Path

import click
import yaml

from quarry.config import settings
from quarry.models import Company, UserSearchQuery
from quarry.store.db import Database, init_db

log = logging.getLogger(__name__)


def load_seed_data(
    seed_path: str | None = None,
) -> tuple[list[Company], list[UserSearchQuery]]:
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
            )
        )

    queries = []
    for q in queries_data:
        queries.append(
            UserSearchQuery(
                user_id=1,
                query_text=q["query_text"],
                site=q.get("site"),
                active=q.get("active", True),
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
        company_id = db.insert_company(company)
        existing_companies.add(company.name.lower())
        log.info("Seeded company: %s", company.name)
        # Upsert watchlist with per-user fields from seed data
        watchlist = db.get_watchlist(user_id=1, active_only=False)
        for wi in watchlist:
            if wi.company_id == company_id:
                wi.crawl_priority = 5
                wi.notes = None
                wi.added_reason = "seed"
                db.upsert_watchlist_item(wi)
                break
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
    from sqlalchemy import update

    from quarry.pipeline.locations import parse_location
    from quarry.store.models import JobPosting as ORMPosting
    from quarry.store.session import session_scope

    db = init_db(settings.db_path)

    postings = db.get_postings()
    postings_with_locations = [p for p in postings if p.location]
    click.echo(f"Found {len(postings_with_locations)} postings with locations")

    locations_created = 0
    links_created = 0
    unresolvable = 0

    for posting in postings_with_locations:
        parse_result = parse_location(posting.location)

        if parse_result.work_model and not posting.work_model:
            if not dry_run:
                with session_scope(engine=db.engine) as session:
                    session.execute(
                        update(ORMPosting)
                        .where(ORMPosting.id == posting.id)
                        .values(work_model=parse_result.work_model)
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


@cli.command(name="recompute-similarity")
def recompute_similarity_command():
    """Recompute all similarity scores against the current ideal role embedding."""
    db = init_db(settings.db_path)
    recompute_similarity(db)
    click.echo("Similarity recomputation complete.")


def recompute_similarity(db: Database | None = None, user_id: int = 1) -> None:
    """Recompute all similarity scores against the current ideal role embedding."""
    from quarry.pipeline.embedder import (
        deserialize_embedding,
        get_ideal_embedding,
    )
    from quarry.pipeline.filter import cosine_similarity

    if db is None:
        db = Database(settings.db_path)

    from quarry.agent.scheduler import _ensure_ideal_embedding

    _ensure_ideal_embedding(db, user_id)
    ideal_embedding = get_ideal_embedding(db, user_id)
    if ideal_embedding is None:
        print("No ideal role embedding found. Set ideal_role_description in config.")
        return

    postings = db.get_all_postings_with_embeddings()
    if not postings:
        print("No postings with embeddings found.")
        return

    updates = []
    skipped = 0
    for p in postings:
        if p.embedding is None:
            skipped += 1
            continue
        emb = deserialize_embedding(p.embedding)
        score = cosine_similarity(emb, ideal_embedding)
        updates.append((p.id, round(score, 4)))

    db.update_posting_similarities(updates, user_id=user_id)
    print(
        f"Updated {len(updates)} posting similarity scores. "
        f"Skipped {skipped} postings with no embedding."
    )


if __name__ == "__main__":
    cli()
