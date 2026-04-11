import pytest

from quarry.models import Company
from quarry.resolve.domain_resolver import normalize_name, resolve_domain


@pytest.mark.asyncio
async def test_resolve_domain_skip_if_already_set():
    company = Company(name="Test", domain="test.com")
    client = None
    result = await resolve_domain(company, client)
    assert result == "test.com"


def test_normalize_name_strips_suffixes():
    assert normalize_name("Acme Inc.") == "acme"
    assert normalize_name("Big Corp LLC") == "big"
    assert normalize_name("Takeda Pharmaceuticals Co.") == "takeda pharmaceuticals"
    assert normalize_name("Global Group Holdings") == "global"
    assert normalize_name("Simple.com") == "simple"
    assert normalize_name("Foo Bar Inc") == "foo bar"


def test_normalize_name_lowercase_and_strip():
    assert normalize_name("  ACME Corp  ") == "acme"


@pytest.mark.asyncio
async def test_resolve_domain_guess_and_probe_success(httpx_mock):
    from quarry.http import close_client, get_client

    httpx_mock.add_response(url="https://acme.com", method="HEAD", status_code=200)
    client = get_client()
    company = Company(name="Acme Inc.")
    try:
        result = await resolve_domain(company, client)
        assert result == "acme.com"
    finally:
        await close_client()


@pytest.mark.asyncio
async def test_resolve_domain_hyphen_transformation(httpx_mock):
    from quarry.http import close_client, get_client

    httpx_mock.add_response(
        url="https://takeda-pharmaceuticals.com", method="HEAD", status_code=200
    )
    httpx_mock.add_response(
        url="https://takedapharmaceuticals.com", method="HEAD", status_code=404
    )
    client = get_client()
    company = Company(name="Takeda Pharmaceuticals Co.")
    try:
        result = await resolve_domain(company, client)
        assert result == "takeda-pharmaceuticals.com"
    finally:
        await close_client()


@pytest.mark.asyncio
async def test_resolve_domain_returns_none_if_nothing_works(httpx_mock):
    from quarry.http import close_client, get_client

    httpx_mock.add_response(
        url="https://unknownstartup.com", method="HEAD", status_code=404
    )
    client = get_client()
    company = Company(name="UnknownStartup Inc.")
    try:
        result = await resolve_domain(company, client)
        assert result is None
    finally:
        await close_client()
