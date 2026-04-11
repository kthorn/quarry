import pytest

from quarry.resolve.ats_detector import detect_ats, detect_ats_url_patterns


def test_detect_ats_url_patterns_greenhouse():
    ats_type, slug = detect_ats_url_patterns("https://boards.greenhouse.io/takeda")
    assert ats_type == "greenhouse"
    assert slug == "takeda"


def test_detect_ats_url_patterns_greenhouse_api():
    ats_type, slug = detect_ats_url_patterns(
        "https://boards-api.greenhouse.io/v1/boards/takeda"
    )
    assert ats_type == "greenhouse"
    assert slug == "takeda"


def test_detect_ats_url_patterns_lever():
    ats_type, slug = detect_ats_url_patterns("https://jobs.lever.co/NimbleAI")
    assert ats_type == "lever"
    assert slug == "NimbleAI"


def test_detect_ats_url_patterns_ashby():
    ats_type, slug = detect_ats_url_patterns("https://jobs.ashbyhq.com/cognition")
    assert ats_type == "ashby"
    assert slug == "cognition"


def test_detect_ats_url_patterns_no_match():
    ats_type, slug = detect_ats_url_patterns("https://example.com/careers")
    assert ats_type == "unknown"
    assert slug is None


def test_detect_ats_url_patterns_no_bare_ashbyhq_domain():
    ats_type, slug = detect_ats_url_patterns("https://ashbyhq.com/careers")
    assert ats_type == "unknown"
    assert slug is None


@pytest.mark.asyncio
async def test_detect_ats_skips_known_ats():
    from quarry.http import close_client, get_client
    from quarry.models import Company

    client = get_client()
    company = Company(name="Test", ats_type="greenhouse", ats_slug="test")
    result = await detect_ats(company, client)
    assert result == ("greenhouse", "test")
    await close_client()


@pytest.mark.asyncio
async def test_detect_ats_skips_generic():
    from quarry.http import close_client, get_client
    from quarry.models import Company

    client = get_client()
    company = Company(name="Test", ats_type="generic")
    result = await detect_ats(company, client)
    assert result == ("generic", None)
    await close_client()


@pytest.mark.asyncio
async def test_detect_ats_skips_no_careers_url():
    from quarry.http import close_client, get_client
    from quarry.models import Company

    client = get_client()
    company = Company(name="Test")
    result = await detect_ats(company, client)
    assert result == ("unknown", None)
    await close_client()


@pytest.mark.asyncio
async def test_detect_ats_url_pattern_fast_path():
    from quarry.http import close_client, get_client
    from quarry.models import Company

    client = get_client()
    company = Company(
        name="Greenhouse Co", careers_url="https://boards.greenhouse.io/myco"
    )
    result = await detect_ats(company, client)
    assert result == ("greenhouse", "myco")
    await close_client()


@pytest.mark.asyncio
async def test_detect_ats_html_signature(httpx_mock):
    from quarry.http import close_client, get_client
    from quarry.models import Company

    httpx_mock.add_response(
        url="https://example.com/careers",
        status_code=200,
        text='<html><script src="https://boards.greenhouse.io/embed.js"></script></html>',
    )
    client = get_client()
    company = Company(
        name="Example Co",
        domain="example.com",
        careers_url="https://example.com/careers",
    )
    result = await detect_ats(company, client)
    assert result[0] == "greenhouse"
    assert result[1] is not None
    await close_client()


@pytest.mark.asyncio
async def test_detect_ats_generic_fallback(httpx_mock):
    from quarry.http import close_client, get_client
    from quarry.models import Company

    httpx_mock.add_response(
        url="https://example.com/careers",
        status_code=200,
        text="<html><body>Some generic careers page</body></html>",
    )
    client = get_client()
    company = Company(
        name="Example Co",
        domain="example.com",
        careers_url="https://example.com/careers",
    )
    result = await detect_ats(company, client)
    assert result == ("generic", None)
    await close_client()


@pytest.mark.asyncio
async def test_detect_ats_html_fetch_failure_returns_unknown(httpx_mock):
    import httpx

    from quarry.http import close_client, get_client
    from quarry.models import Company

    httpx_mock.add_exception(
        httpx.ConnectTimeout("timeout"), url="https://example.com/careers"
    )
    client = get_client()
    company = Company(
        name="Example Co",
        domain="example.com",
        careers_url="https://example.com/careers",
    )
    result = await detect_ats(company, client)
    assert result == ("unknown", None)
    await close_client()
