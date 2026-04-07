# quarry/crawlers/__init__.py
"""Crawlers for job postings."""

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quarry.models import Company

from quarry.crawlers.ashby import AshbyCrawler
from quarry.crawlers.base import BaseCrawler
from quarry.crawlers.careers_page import CareersPageCrawler
from quarry.crawlers.greenhouse import GreenhouseCrawler
from quarry.crawlers.lever import LeverCrawler


class CrawlerType(str, Enum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    CAREERS_PAGE = "careers_page"


def get_crawler(company: "Company") -> BaseCrawler:
    """Get appropriate crawler for company based on ats_type.

    Args:
        company: Company to get crawler for

    Returns:
        Appropriate crawler instance
    """
    ats_type = company.ats_type

    if ats_type == "greenhouse":
        return GreenhouseCrawler()
    elif ats_type == "lever":
        return LeverCrawler()
    elif ats_type == "ashby":
        return AshbyCrawler()
    else:
        return CareersPageCrawler()
