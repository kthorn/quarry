import asyncio
import logging

import click

from quarry.config import settings
from quarry.store.db import Database, init_db

log = logging.getLogger(__name__)


@click.group()
def cli():
    """Resolve company domains, careers URLs, and ATS types."""
    pass


@cli.command()
@click.option(
    "--retry-failed", is_flag=True, help="Also retry previously failed companies"
)
@click.option("--company", "company_name", help="Resolve a single company by name")
@click.option(
    "--redetect-ats", is_flag=True, help="Re-run ATS detection on generic companies"
)
def resolve(retry_failed: bool, company_name: str | None, redetect_ats: bool) -> None:
    """Resolve all unresolved companies (domain, careers URL, ATS type)."""
    _configure_logging()
    db = init_db(settings.db_path)

    if company_name:
        company = db.get_company_by_name(company_name)
        if not company:
            click.echo(f"Company not found: {company_name}")
            return
        click.echo(f"Resolving company: {company.name}")
        from quarry.resolve.pipeline import resolve_company

        result = asyncio.run(resolve_company(company, db=db))
        click.echo(
            f"Result: domain={result.domain}, careers_url={result.careers_url}, "
            f"ats_type={result.ats_type}, status={result.resolve_status}"
        )
        return

    if redetect_ats:
        click.echo("Re-detecting ATS types...")
        _redetect_ats(db)
        return

    from quarry.resolve.pipeline import resolve_unresolved

    click.echo("Resolving unresolved companies...")
    asyncio.run(resolve_unresolved(db))

    if retry_failed:
        click.echo("Retrying failed companies...")
        companies = db.get_companies_by_resolve_status("failed")
        for company in companies:
            company.resolve_status = "unresolved"
            company.resolve_attempts = 0
            db.update_company(company)
        asyncio.run(resolve_unresolved(db))

    unresolved = db.get_companies_by_resolve_status("unresolved")
    resolved = db.get_companies_by_resolve_status("resolved")
    failed = db.get_companies_by_resolve_status("failed")
    click.echo(
        f"Resolved: {len(resolved)}, Unresolved: {len(unresolved)}, Failed: {len(failed)}"
    )


def _redetect_ats(db: Database) -> None:
    companies = db.get_all_companies(active_only=False)
    updated = 0
    for company in companies:
        if company.careers_url and company.ats_type in ("generic", "unknown"):
            company.ats_type = "unknown"
            company.ats_slug = None
            company.resolve_status = "unresolved"
            db.update_company(company)
            updated += 1
    if updated > 0:
        from quarry.resolve.pipeline import resolve_unresolved

        asyncio.run(resolve_unresolved(db))
    click.echo(f"Re-detecting ATS for {updated} companies")


def _configure_logging():
    logging.basicConfig(
        level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


if __name__ == "__main__":
    cli()
