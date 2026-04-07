import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from quarry.crawlers.lever import LeverCrawler
from quarry.models import Company


@pytest.fixture
def company():
    return Company(
        id=2,
        name="Test Corp",
        ats_type="lever",
        ats_slug="testcorp",
        careers_url="https://jobs.lever.co/testcorp",
    )


@pytest.fixture
def sample_response():
    fixture_path = Path(__file__).parent / "fixtures" / "lever_response.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.mark.asyncio
async def test_lever_crawl_parses_jobs(company, sample_response):
    crawler = LeverCrawler()

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_response
        mock_get.return_value = mock_response

        postings = await crawler.crawl(company)

    assert len(postings) == 2
    assert postings[0].title == "Software Engineer"
    assert postings[0].source_type == "lever"
    assert postings[0].source_id == "abc123"
