import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from quarry.crawlers.greenhouse import GreenhouseCrawler
from quarry.models import Company


@pytest.fixture
def company():
    return Company(
        id=1,
        name="Test Corp",
        ats_type="greenhouse",
        ats_slug="testcorp",
        careers_url="https://boards.greenhouse.io/testcorp",
    )


@pytest.fixture
def sample_response():
    fixture_path = Path(__file__).parent / "fixtures" / "greenhouse_response.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.mark.asyncio
async def test_greenhouse_crawl_parses_jobs(company, sample_response):
    crawler = GreenhouseCrawler()

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_response
        mock_get.return_value = mock_response

        postings = await crawler.crawl(company)

    assert len(postings) == 2
    assert postings[0].title == "Senior Software Engineer"
    assert postings[0].source_type == "greenhouse"
    assert postings[0].source_id == "12345"
    assert postings[0].url == "https://boards.greenhouse.io/testcorp/jobs/12345"


@pytest.mark.asyncio
async def test_greenhouse_returns_empty_for_empty_response(company):
    crawler = GreenhouseCrawler()

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"jobs": []}
        mock_get.return_value = mock_response

        postings = await crawler.crawl(company)

    assert postings == []
