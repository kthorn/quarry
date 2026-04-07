from quarry.crawlers.base import BaseCrawler, get_retry_decorator


def test_retry_decorator_exists():
    assert get_retry_decorator is not None


def test_base_crawler_has_retry_config():
    class TestCrawler(BaseCrawler):
        async def crawl(self, company):
            return []

    crawler = TestCrawler(max_retries=3, retry_base_delay=2)
    assert crawler.max_retries == 3
    assert crawler.retry_base_delay == 2
