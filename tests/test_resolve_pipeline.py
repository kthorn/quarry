import asyncio
import os
from unittest.mock import Mock, patch

import pytest

from quarry.models import Company
from quarry.store.db import init_db


@pytest.mark.asyncio
async def test_resolve_companies_batch_respects_semaphore():
    """Only max_concurrent resolutions run at once."""
    db = Mock()
    companies = [Company(name=f"Co{i}", id=i) for i in range(5)]

    active_count = 0
    max_observed = 0

    async def fake_resolve(company, db=None, client=None):
        nonlocal active_count, max_observed
        active_count += 1
        max_observed = max(max_observed, active_count)
        await asyncio.sleep(0.01)
        active_count -= 1

    with patch("quarry.resolve.pipeline.resolve_company", side_effect=fake_resolve):
        from quarry.resolve.pipeline import resolve_companies_batch

        await resolve_companies_batch(db, companies, max_concurrent=2)

    assert max_observed <= 2


@pytest.mark.skip(reason="Phase 4 — production code needs per-user field updates")
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


@pytest.mark.skip(reason="Phase 4 — production code needs per-user field updates")
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


@pytest.mark.skip(reason="Phase 4 — production code needs per-user field updates")
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
