# quarry/crawlers/base.py
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from quarry.config import settings
from quarry.models import Company, RawPosting

if TYPE_CHECKING:
    from quarry.models import Company, RawPosting


def should_retry(exception: Exception) -> bool:
    """Determine if exception should trigger retry."""
    if isinstance(exception, httpx.TimeoutException):
        return True
    if isinstance(exception, httpx.ConnectError):
        return True
    if isinstance(exception, httpx.HTTPStatusError):
        status = exception.response.status_code
        if status == 429:
            return True
        if 500 <= status < 600:
            return True
    return False


def get_retry_decorator(max_retries: int | None = None, base_delay: int | None = None):
    """Create retry decorator with config."""
    max_retries = max_retries or settings.max_retries
    base_delay = base_delay or settings.retry_base_delay

    return retry(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=base_delay, min=1, max=30),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
        reraise=True,
    )


class BaseCrawler(ABC):
    """Abstract base class for ATS crawlers."""

    def __init__(
        self, max_retries: int | None = None, retry_base_delay: int | None = None
    ):
        self.max_retries = max_retries or settings.max_retries
        self.retry_base_delay = retry_base_delay or settings.retry_base_delay
        self.request_timeout = settings.request_timeout

    @abstractmethod
    async def crawl(self, company: "Company") -> list["RawPosting"]:
        """Crawl jobs for a company.

        Args:
            company: Company to crawl

        Returns:
            List of RawPosting objects
        """
        pass
