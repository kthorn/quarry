import asyncio
import logging

import httpx

from quarry.http import close_client, get_client
from quarry.models import Company
from quarry.resolve.ats_detector import detect_ats
from quarry.resolve.careers_resolver import resolve_careers_url
from quarry.resolve.domain_resolver import resolve_domain
from quarry.store.db import Database

log = logging.getLogger(__name__)

MAX_RESOLVE_ATTEMPTS = 3


async def resolve_company(
    company: Company,
    db: Database | None = None,
    client: httpx.AsyncClient | None = None,
) -> Company:
    if company.resolve_status == "resolved":
        return company

    if client is None:
        client = get_client()

    domain_changed = False
    careers_changed = False

    if not company.domain:
        domain = await resolve_domain(company, client)
        if domain:
            company.domain = domain
            company.resolve_attempts = 0
            domain_changed = True
        else:
            company.resolve_attempts += 1
            if company.resolve_attempts >= MAX_RESOLVE_ATTEMPTS:
                company.resolve_status = "failed"
                log.warning(
                    "Marking %s as failed after %d attempts",
                    company.name,
                    company.resolve_attempts,
                )
            if db:
                db.update_company(company)
            return company

    if not company.careers_url and company.domain:
        careers_url = await resolve_careers_url(company, client)
        if careers_url:
            company.careers_url = careers_url
            company.resolve_attempts = 0
            careers_changed = True
        else:
            company.resolve_attempts += 1
            if company.resolve_attempts >= MAX_RESOLVE_ATTEMPTS:
                company.resolve_status = "failed"
                log.warning(
                    "Marking %s as failed after %d attempts",
                    company.name,
                    company.resolve_attempts,
                )
            if db:
                db.update_company(company)
            return company

    if company.careers_url and company.ats_type == "unknown":
        ats_type, ats_slug = await detect_ats(company, client)
        company.ats_type = ats_type
        company.ats_slug = ats_slug
        if ats_type == "unknown":
            if db:
                db.update_company(company)
            return company
        company.resolve_status = "resolved"
        log.info(
            "Resolved %s: ats_type=%s, ats_slug=%s", company.name, ats_type, ats_slug
        )
    elif company.careers_url and company.ats_type != "unknown":
        company.resolve_status = "resolved"

    if domain_changed or careers_changed or company.resolve_status == "resolved":
        if db:
            db.update_company(company)

    return company


async def resolve_unresolved(
    db: Database, client: httpx.AsyncClient | None = None
) -> None:
    if client is None:
        client = get_client()

    try:
        companies = db.get_companies_by_resolve_status("unresolved")
        log.info("Resolving %d unresolved companies", len(companies))
        for company in companies:
            try:
                await resolve_company(company, db=db, client=client)
            except Exception as e:
                log.error("Error resolving %s: %s", company.name, e)
    finally:
        await close_client()


async def resolve_companies_batch(
    db: Database,
    companies: list[Company],
    max_concurrent: int = 3,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Resolve a batch of companies with concurrency gating.

    Accepts an optional external client. If none is provided, a new client
    is created and closed when the batch completes.
    """
    should_close = client is None
    if client is None:
        client = get_client()

    try:
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _resolve_one(company: Company) -> None:
            async with semaphore:
                try:
                    await resolve_company(company, db=db, client=client)
                except Exception as e:
                    log.error("Error resolving %s: %s", company.name, e)

        await asyncio.gather(*[_resolve_one(c) for c in companies])
    finally:
        if should_close:
            await close_client()


def resolve_unresolved_sync(
    db: Database,
    max_concurrent: int = 3,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Synchronous entrypoint to resolve all unresolved companies.

    Accepts an optional external client (passed through to resolve_companies_batch).

    Uses asyncio.run() which creates a fresh event loop. This is safe as long
    as the caller is not already inside a running event loop (which the current
    synchronous scheduler is not). If the scheduler ever becomes async, refactor
    to call resolve_companies_batch directly instead of using this wrapper.
    """
    companies = db.get_companies_by_resolve_status("unresolved")
    if not companies:
        return
    log.info(
        "Resolving %d unresolved companies (max_concurrent=%d)",
        len(companies),
        max_concurrent,
    )
    asyncio.run(
        resolve_companies_batch(
            db, companies, max_concurrent=max_concurrent, client=client
        )
    )


def resolve_company_sync(
    company: Company,
    db: Database | None = None,
    client: httpx.AsyncClient | None = None,
) -> Company:
    """Synchronous entrypoint to resolve a single company.

    Uses asyncio.run() which creates a fresh event loop. Any internally-created
    HTTP client is bound to that loop's lifecycle and cleaned up on exit.
    Repeated calls create/destroy event loops — acceptable for the current
    single-user CLI/UI tool. If called frequently from a long-running server,
    refactor to use a shared client and event loop.
    """

    async def _resolve() -> Company:
        try:
            return await resolve_company(company, db=db, client=client)
        finally:
            await close_client()

    return asyncio.run(_resolve())
