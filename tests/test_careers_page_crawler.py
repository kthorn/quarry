import pytest

from quarry.crawlers.careers_page import CareersPageCrawler
from quarry.models import Company


@pytest.fixture
def company():
    return Company(
        id=4,
        name="Test Corp",
        ats_type="unknown",
        careers_url="https://example.com/careers",
    )


@pytest.mark.asyncio
async def test_careers_page_rejects_http_not_https():
    crawler = CareersPageCrawler()
    company = Company(id=1, name="Test", careers_url="http://example.com/careers")

    postings = await crawler.crawl(company)
    assert postings == []


@pytest.mark.asyncio
async def test_careers_page_rejects_private_ip():
    crawler = CareersPageCrawler()
    company = Company(id=1, name="Test", careers_url="http://192.168.1.1/careers")

    postings = await crawler.crawl(company)
    assert postings == []
