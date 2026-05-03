import asyncio

import click

from quarry.config import settings
from quarry.models import Company
from quarry.resolve.ats_detector import detect_ats_url_patterns
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

    if company.resolve_status != "resolved" and not careers_url:
        from quarry.resolve.pipeline import resolve_company

        result = asyncio.run(resolve_company(company, db=db))
        click.echo(
            f"Resolved: domain={result.domain}, careers_url={result.careers_url}, "
            f"ats_type={result.ats_type}, status={result.resolve_status}"
        )

    from quarry.http import close_client

    asyncio.run(close_client())


if __name__ == "__main__":
    cli()
