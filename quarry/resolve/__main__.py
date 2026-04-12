import asyncio
import logging

import click

from quarry.config import settings
from quarry.models import Company
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
        if redetect_ats:
            click.echo(f"Re-detecting ATS for company: {company.name}")
            _redetect_ats_for_company(company, db)
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


@cli.command()
@click.option("--company", "company_name", help="Scan a single company by name")
@click.option("--yes", "-y", is_flag=True, help="Apply all changes without prompting")
def detect_ats_links(company_name: str | None, yes: bool) -> None:
    """Scan careers pages for ATS board links and propose updates.

    For each company with ats_type 'generic' or 'unknown', fetches the
    careers page and looks for links to known ATS domains (Greenhouse,
    Lever, Ashby). If found, proposes updating ats_type and ats_slug.
    Confirms before writing changes unless --yes is given.
    """
    _configure_logging()
    db = init_db(settings.db_path)

    companies = _get_target_companies(db, company_name)
    if not companies:
        click.echo("No companies to scan.")
        return

    proposed = asyncio.run(_scan_companies(companies))

    if not proposed:
        click.echo("\nNo ATS board links detected in any careers pages.")
        return

    click.echo(f"\nFound {len(proposed)} ATS board(s):\n")
    click.echo(
        f"{'Company':<25s} {'Current':<12s} {'Detected':<12s} "
        f"{'Slug':<20s} {'Careers URL'}"
    )
    click.echo("-" * 110)
    for item in proposed:
        click.echo(
            f"{item['company'].name:<25s} {item['old_ats_type'] or 'unknown':<12s} "
            f"{item['new_ats_type']:<12s} {item['new_ats_slug'] or '':<20s} "
            f"{item['company'].careers_url or ''}"
        )

    if yes:
        _apply_changes(db, proposed)
        return

    click.echo()
    if not click.confirm("Apply these changes?"):
        click.echo("Aborted.")
        return

    _apply_changes(db, proposed)


def _get_target_companies(db: Database, company_name: str | None) -> list[Company]:
    if company_name:
        company = db.get_company_by_name(company_name)
        if not company:
            click.echo(f"Company not found: {company_name}")
            return []
        return [company]

    companies = db.get_all_companies(active_only=True)
    return [
        c for c in companies if c.ats_type in ("generic", "unknown") and c.careers_url
    ]


async def _scan_companies(companies: list[Company]) -> list[dict]:
    from urllib.parse import urlparse

    from quarry.crawlers.careers_page import (
        _get_host_ip,
        _is_private_ip,
        _LinkExtractor,
        detect_ats_from_links,
    )
    from quarry.http import close_client, get_client

    client = get_client()
    proposed: list[dict] = []

    try:
        for company in companies:
            click.echo(f"Scanning {company.name}...", nl=False)
            url = company.careers_url
            if not url:
                click.echo(" no careers_url")
                continue

            parsed = urlparse(url)
            hostname = parsed.hostname
            if not hostname or parsed.scheme != "https":
                click.echo(" skipped (no hostname / not https)")
                continue
            ip = _get_host_ip(hostname)
            if ip and _is_private_ip(ip):
                click.echo(" blocked (private IP)")
                continue

            try:
                extractor = _LinkExtractor()
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > 5 * 1024 * 1024:
                            break
                        try:
                            extractor.feed(chunk.decode("utf-8", errors="ignore"))
                        except Exception:
                            pass
                extractor.close()

                detected = detect_ats_from_links(extractor.links)
                if detected:
                    ats_type, ats_slug = detected
                    click.echo(f" found {ats_type}/{ats_slug}")
                    proposed.append(
                        {
                            "company": company,
                            "old_ats_type": company.ats_type,
                            "new_ats_type": ats_type,
                            "new_ats_slug": ats_slug,
                        }
                    )
                else:
                    click.echo(" no ATS board found")
            except Exception as e:
                click.echo(f" error: {e}")
    finally:
        await close_client()

    return proposed


def _apply_changes(db: Database, proposed: list[dict]) -> None:
    for item in proposed:
        company = item["company"]
        company.ats_type = item["new_ats_type"]
        company.ats_slug = item["new_ats_slug"]
        company.resolve_status = "resolved"
        db.update_company(company)
        click.echo(
            f"Updated {company.name}: ats_type={company.ats_type}, "
            f"ats_slug={company.ats_slug}"
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


def _redetect_ats_for_company(company: Company, db: Database) -> None:
    """Reset ATS type for a single company and re-resolve it."""
    company.ats_type = "unknown"
    company.ats_slug = None
    company.resolve_status = "unresolved"
    company.resolve_attempts = 0
    db.update_company(company)

    from quarry.resolve.pipeline import resolve_company

    result = asyncio.run(resolve_company(company, db=db))
    click.echo(
        f"Result: domain={result.domain}, careers_url={result.careers_url}, "
        f"ats_type={result.ats_type}, ats_slug={result.ats_slug}, "
        f"status={result.resolve_status}"
    )


def _configure_logging():
    logging.basicConfig(
        level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


if __name__ == "__main__":
    cli()
