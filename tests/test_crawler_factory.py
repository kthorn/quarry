from quarry.crawlers import get_crawler
from quarry.models import Company


def test_get_crawler_for_greenhouse():
    company = Company(name="Test", ats_type="greenhouse", ats_slug="test")
    crawler = get_crawler(company)
    assert crawler.__class__.__name__ == "GreenhouseCrawler"


def test_get_crawler_for_unknown_uses_careers_page():
    company = Company(
        name="Test", ats_type="unknown", careers_url="https://test.com/careers"
    )
    crawler = get_crawler(company)
    assert crawler.__class__.__name__ == "CareersPageCrawler"


def test_get_crawler_for_generic_uses_careers_page():
    company = Company(
        name="Test", ats_type="generic", careers_url="https://test.com/careers"
    )
    crawler = get_crawler(company)
    assert crawler.__class__.__name__ == "CareersPageCrawler"
