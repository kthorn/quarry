from abc import ABC
from quarry.crawlers.base import BaseCrawler


def test_base_crawler_is_abc():
    assert issubclass(BaseCrawler, ABC)


def test_base_crawler_has_abstract_method():
    # Should have crawl method
    assert hasattr(BaseCrawler, "crawl")
