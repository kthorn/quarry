import sys
from pathlib import Path

import click

from quarry.config import settings
from quarry.models import Company
from quarry.rank.train import _MODELS_DIR
from quarry.resolve.ats_detector import detect_ats_url_patterns
from quarry.resolve.pipeline import resolve_company_sync
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


@cli.command("add-company")
@click.option("--name", required=True, help="Company name")
@click.option("--domain", default=None, help="Company domain (e.g. example.com)")
@click.option(
    "--careers-url",
    default=None,
    help="Careers page URL (e.g. https://example.com/careers)",
)
def add_company(name: str, domain: str | None, careers_url: str | None) -> None:
    """Add a company to the database and optionally resolve its ATS type."""
    db = init_db(settings.db_path)

    existing = db.get_company_by_name(name)
    if existing:
        click.echo(f"Company already exists: {name} (id={existing.id})")
        return

    company = Company(
        name=name,
        domain=domain,
        careers_url=careers_url,
        ats_type="unknown",
    )

    if careers_url:
        from urllib.parse import urlparse

        parsed = urlparse(careers_url)
        if parsed.scheme not in ("http", "https"):
            click.echo(f"Invalid URL scheme: {careers_url}")
            return
        if not parsed.hostname:
            click.echo(f"Invalid URL: {careers_url}")
            return

        ats_type, ats_slug = detect_ats_url_patterns(careers_url)
        if ats_type != "unknown":
            company.ats_type = ats_type
            company.ats_slug = ats_slug
            company.resolve_status = "resolved"
            click.echo(f"Detected ATS: {ats_type} (slug: {ats_slug})")
        else:
            company.resolve_status = "unresolved"

    if domain and not careers_url and not company.resolve_status == "resolved":
        import re

        if not re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*\.)+[a-zA-Z]{2,}$", domain):
            click.echo(f"Invalid domain: {domain}")
            return

    company.id = db.insert_company(company)
    click.echo(f"Added company: {name} (id={company.id})")

    # Generate description for newly added company
    try:
        from quarry.resolve.description import generate_company_description

        desc, source = generate_company_description(company)
        db.update_company_description(company.id, desc, source)
        click.echo(f"Generated description ({source})")
    except Exception:
        click.echo("Description generation failed (will retry later)")

    if company.resolve_status != "resolved" and not careers_url:
        company = resolve_company_sync(company, db=db)
        click.echo(
            f"Resolved: domain={company.domain}, careers_url={company.careers_url}, "
            f"ats_type={company.ats_type}, status={company.resolve_status}"
        )


@cli.command("reset")
@click.option(
    "--keep-companies",
    is_flag=True,
    help="Keep company infrastructure (companies, watchlist, search queries, settings, users).",
)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def reset(keep_companies: bool, yes: bool) -> None:
    """Reset the database, optionally keeping company data."""
    from sqlalchemy import text

    from quarry.store.models import Base
    from quarry.store.session import get_engine, session_scope

    db_path = Path(settings.db_path)

    # Refuse if db file does not exist
    if not db_path.exists():
        click.echo(f"Error: Database file not found at {db_path}", err=True)
        sys.exit(1)

    engine = get_engine(db_path)

    # Query live counts for the confirmation prompt
    with session_scope(engine=engine) as session:
        posting_count = (
            session.execute(text("SELECT COUNT(*) FROM job_postings")).scalar() or 0
        )
        label_count = (
            session.execute(text("SELECT COUNT(*) FROM user_posting_state")).scalar()
            or 0
        )
        model_count = (
            session.execute(text("SELECT COUNT(*) FROM classifier_versions")).scalar()
            or 0
        )
        crawl_count = (
            session.execute(text("SELECT COUNT(*) FROM crawl_runs")).scalar() or 0
        )
        company_count = (
            session.execute(text("SELECT COUNT(*) FROM companies")).scalar() or 0
        )
        watchlist_count = (
            session.execute(text("SELECT COUNT(*) FROM user_watchlist")).scalar() or 0
        )
        search_count = (
            session.execute(text("SELECT COUNT(*) FROM user_search_queries")).scalar()
            or 0
        )
        setting_count = (
            session.execute(text("SELECT COUNT(*) FROM user_settings")).scalar() or 0
        )

    # Confirmation prompt (unless --yes)
    if not yes:
        if keep_companies:
            msg = (
                f"This will delete {posting_count} postings, {label_count} labels, "
                f"{model_count} classifier models, and {crawl_count} crawl runs "
                f"(keeping {company_count} companies, {watchlist_count} watchlist items, "
                f"{search_count} search queries, and {setting_count} settings). "
                f"Type 'reset' to confirm"
            )
        else:
            msg = (
                f"This will delete ALL data including {company_count} companies, "
                f"{watchlist_count} watchlist items, {search_count} search queries, "
                f"and {setting_count} settings, plus {posting_count} postings, "
                f"{label_count} labels, {model_count} classifier models, "
                f"and {crawl_count} crawl runs. Type 'reset' to confirm"
            )

        answer = click.prompt(msg, default="", show_default=False)
        if answer != "reset":
            click.echo("Aborted.")
            sys.exit(1)

    # Remove classifier .pkl files
    pkl_count = 0
    for pkl_file in _MODELS_DIR.glob("classifier_*.pkl"):
        pkl_file.unlink()
        click.echo(f"Removed model file: {pkl_file.name}")
        pkl_count += 1

    # Delete from database
    if keep_companies:
        # FK-safe order: children before parents
        delete_tables = [
            ("user_posting_state", "labels"),
            ("user_similarity_scores", "similarity scores"),
            ("user_classifier_scores", "classifier scores"),
            ("user_enriched_postings", "enriched postings"),
            ("user_ranking_scores", "ranking scores"),
            ("job_posting_locations", "posting locations"),
            ("job_postings", "postings"),
            ("classifier_versions", "classifier versions"),
            ("crawl_runs", "crawl runs"),
        ]

        with session_scope(engine=engine) as session:
            for table, label in delete_tables:
                result = session.execute(text(f"DELETE FROM {table}"))
                count = result.rowcount  # type: ignore[attr-defined]
                click.echo(f"Deleted {count} {label}")
    else:
        # Full reset: drop all, recreate, then re-seed via init_db
        Base.metadata.drop_all(engine)
        init_db(db_path)
        click.echo("All tables dropped and recreated.")
        click.echo("Default user re-seeded.")

    click.echo(f"Removed {pkl_count} classifier model file(s) from {_MODELS_DIR}")


if __name__ == "__main__":
    cli()
