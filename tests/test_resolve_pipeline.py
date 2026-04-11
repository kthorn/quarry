import os

import pytest

from quarry.models import Company
from quarry.store.db import init_db


@pytest.mark.asyncio
async def test_resolve_company_skips_already_resolved():
    from quarry.http import close_client
    from quarry.resolve.pipeline import resolve_company

    company = Company(
        name="Resolved Co",
        domain="resolved.com",
        careers_url="https://resolved.com/careers",
        ats_type="greenhouse",
        ats_slug="resolved",
        resolve_status="resolved",
    )
    result = await resolve_company(company, db=None)
    assert result.resolve_status == "resolved"
    await close_client()


@pytest.mark.asyncio
async def test_resolve_company_sets_failed_after_max_attempts(httpx_mock):
    from quarry.http import close_client, get_client
    from quarry.resolve.pipeline import resolve_company

    db_path = "/tmp/test_resolve_pipeline1.db"

    if os.path.exists(db_path):
        os.remove(db_path)
    db = init_db(db_path)

    httpx_mock.add_response(url="https://failcorp.com", method="HEAD", status_code=404)

    company = Company(name="FailCorp Inc.", resolve_attempts=2)
    company.id = db.insert_company(company)
    client = get_client()

    try:
        result = await resolve_company(company, db=db, client=client)
        assert result.resolve_status == "failed"
        assert result.resolve_attempts == 3
        assert result.domain is None
    finally:
        await close_client()
        os.remove(db_path)


@pytest.mark.asyncio
async def test_resolve_unresolved_processes_unresolved_companies(httpx_mock):
    from quarry.http import close_client
    from quarry.resolve.pipeline import resolve_unresolved

    db_path = "/tmp/test_resolve_pipeline2.db"

    if os.path.exists(db_path):
        os.remove(db_path)
    db = init_db(db_path)

    httpx_mock.add_response(url="https://acme.com", method="HEAD", status_code=200)
    httpx_mock.add_response(
        url="https://acme.com/careers",
        status_code=200,
        text="<html><body>Job openings at ACME</body></html>",
    )
    httpx_mock.add_response(
        url="https://acme.com/careers",
        status_code=200,
        text="<html><body>Job openings at ACME</body></html>",
    )

    company = Company(name="Acme Inc.")
    db.insert_company(company)

    try:
        await resolve_unresolved(db)
        companies = db.get_all_companies(active_only=False)
        assert len(companies) == 1
        assert companies[0].domain == "acme.com"
    finally:
        await close_client()
        os.remove(db_path)
