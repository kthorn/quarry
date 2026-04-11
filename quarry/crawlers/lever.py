# quarry/crawlers/lever.py
import logging
from typing import Any

import httpx

from quarry.crawlers.base import BaseCrawler, Crawl404Error
from quarry.http import get_client
from quarry.models import Company, RawPosting

logger = logging.getLogger(__name__)


class LeverCrawler(BaseCrawler):
    """Crawler for Lever job boards."""

    BASE_URL = "https://api.lever.co/v0/postings"

    async def crawl(self, company: Company) -> list[RawPosting]:
        """Fetch jobs from Lever API."""
        if not company.ats_slug:
            logger.warning(f"Company {company.name} has no ats_slug")
            return []

        url = f"{self.BASE_URL}/{company.ats_slug}?mode=json"
        client = get_client()

        try:
            response = await client.get(url)
            response.raise_for_status()
            jobs = response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise Crawl404Error(company.name, url) from e
            logger.error(f"HTTP error fetching {company.name}: {e}")
            return []
        except httpx.RequestError as e:
            logger.error(f"Request error fetching {company.name}: {e}")
            return []

        return self._parse_jobs(jobs, company.id or 0)

    def _parse_jobs(
        self, jobs: list[dict[str, Any]], company_id: int
    ) -> list[RawPosting]:
        """Parse jobs from Lever API response."""
        postings = []
        for job in jobs:
            categories = job.get("categories", {})

            is_remote = None
            location = categories.get("location", "")
            if location and "remote" in location.lower():
                is_remote = True

            posting = RawPosting(
                company_id=company_id,
                title=job.get("text", ""),
                url=job.get("hostedUrl", ""),
                description=job.get("descriptionPlain"),
                location=location,
                remote=is_remote,
                source_id=job.get("id"),
                source_type="lever",
            )
            postings.append(posting)

        return postings
