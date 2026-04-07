import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

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
    crawler = AshbyCrawler()

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_response
        mock_post.return_value = mock_response

        postings = await crawler.crawl(company)

    assert len(postings) == 1
    assert postings[0].title == "Staff Engineer"
    assert postings[0].source_type == "ashby"
    assert postings[0].source_id == "job_abc123"
