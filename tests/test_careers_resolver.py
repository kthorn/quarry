import pytest

from quarry.models import Company
from quarry.resolve.careers_resolver import resolve_careers_url


@pytest.mark.asyncio
async def test_resolve_careers_url_skip_if_already_set():
    company = Company(name="Test", careers_url="https://test.com/careers")
    client = None
    result = await resolve_careers_url(company, client)
    assert result == "https://test.com/careers"


@pytest.mark.asyncio
async def test_resolve_careers_url_skip_if_no_domain():
    company = Company(name="Test")
    result = await resolve_careers_url(company, None)
    assert result is None


@pytest.mark.asyncio
async def test_resolve_careers_url_probes_patterns(httpx_mock):
    from quarry.http import close_client, get_client

    httpx_mock.add_response(
        url="https://acme.com/careers",
        status_code=200,
        text="<html><body>View our open positions and career opportunities</body></html>",
    )
    client = get_client()
    company = Company(name="Acme", domain="acme.com")
    try:
        result = await resolve_careers_url(company, client)
        assert result is not None
        assert "/careers" in result
    finally:
        await close_client()


@pytest.mark.asyncio
async def test_resolve_careers_url_returns_redirected_url(httpx_mock):
    from quarry.http import close_client, get_client

    httpx_mock.add_response(
        url="https://acme.com/careers",
        status_code=301,
        headers={"Location": "https://acme.com/en/careers"},
    )
    httpx_mock.add_response(
        url="https://acme.com/en/careers",
        status_code=200,
        text="<html><body>Job openings and career paths</body></html>",
    )
    client = get_client()
    company = Company(name="Acme", domain="acme.com")
    try:
        result = await resolve_careers_url(company, client)
        assert result is not None
        assert "acme.com" in result
    finally:
        await close_client()


@pytest.mark.asyncio
async def test_resolve_careers_url_returns_none_if_no_pattern_works(httpx_mock):
    from quarry.http import close_client, get_client

    for domain in ["unknown.com", "www.unknown.com"]:
        for pattern in [
            "/careers",
            "/jobs",
            "/careers/search",
            "/about/careers",
            "/en/careers",
        ]:
            url = f"https://{domain}{pattern}"
            httpx_mock.add_response(url=url, status_code=404)

    client = get_client()
    company = Company(name="Unknown", domain="unknown.com")
    try:
        result = await resolve_careers_url(company, client)
        assert result is None
    finally:
        await close_client()
