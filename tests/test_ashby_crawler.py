import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from quarry.crawlers.ashby import AshbyCrawler
from quarry.models import Company


@pytest.fixture
def company():
    return Company(
        id=3,
        name="Test Corp",
        ats_type="ashby",
        ats_slug="testcorp",
        careers_url="https://jobs.ashbyhq.com/testcorp",
    )


@pytest.fixture
def sample_response():
    fixture_path = Path(__file__).parent / "fixtures" / "ashby_response.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.mark.asyncio
async def test_ashby_crawl_parses_jobs(company, sample_response):
    """Ashby REST posting-api response is parsed into RawPostings."""
    crawler = AshbyCrawler()

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_response
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        postings = await crawler.crawl(company)

    assert len(postings) == 2
    # First job — field mapping from REST shape
    assert postings[0].title == "Staff Engineer"
    assert postings[0].source_type == "ashby"
    assert postings[0].source_id == "job_abc123"
    assert (
        postings[0].url
        == "https://jobs.ashbyhq.com/testcorp/8fb1615c-34bf-47c4-a1d1-b7b2f836bbd3"
    )
    assert postings[0].description == "We are hiring a staff engineer."
    assert postings[0].location == "San Francisco"
    assert postings[0].posted_at == datetime(
        2026, 3, 12, 16, 38, 15, 322000, tzinfo=timezone.utc
    )
    # Second job
    assert postings[1].title == "Remote Developer"
    assert postings[1].source_id == "job_def456"
    assert postings[1].location == "Remote, US"


@pytest.mark.asyncio
async def test_ashby_crawl_hits_posting_api_endpoint(company):
    """The crawler must use Ashby's public REST posting-api, not the deprecated GraphQL endpoint."""
    crawler = AshbyCrawler()

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"apiVersion": "1", "jobs": []}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        await crawler.crawl(company)

    mock_get.assert_called_once()
    called_url = str(mock_get.call_args.args[0])
    assert "api.ashbyhq.com/posting-api/job-board/testcorp" in called_url
    assert "jobs.ashbyhq.com/api/non-user-graphql" not in called_url


@pytest.mark.asyncio
async def test_ashby_crawl_no_slug_returns_empty():
    """A company with no ats_slug logs a warning and returns []."""
    crawler = AshbyCrawler()
    company = Company(id=5, name="No Slug Co", ats_type="ashby", ats_slug=None)
    postings = await crawler.crawl(company)
    assert postings == []


@pytest.mark.asyncio
async def test_ashby_crawl_404_raises(company):
    """A 404 from the posting-api raises Crawl404Error (signals ATS migration)."""
    import httpx

    from quarry.crawlers.base import Crawl404Error

    crawler = AshbyCrawler()

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=MagicMock(status_code=404)
        )
        mock_get.return_value = mock_response

        with pytest.raises(Crawl404Error):
            await crawler.crawl(company)
