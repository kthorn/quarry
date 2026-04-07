# quarry/crawlers/greenhouse.py
import logging
from datetime import datetime
from typing import Any

import httpx

from quarry.crawlers.base import BaseCrawler
from quarry.models import Company, RawPosting

logger = logging.getLogger(__name__)


class GreenhouseCrawler(BaseCrawler):
    """Crawler for Greenhouse job boards."""

    BASE_URL = "https://boards-api.greenhouse.io/v1/boards"

    async def crawl(self, company: Company) -> list[RawPosting]:
        """Fetch jobs from Greenhouse API."""
        if not company.ats_slug:
            logger.warning(f"Company {company.name} has no ats_slug")
            return []

        url = f"{self.BASE_URL}/{company.ats_slug}/jobs?content=true"

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error fetching {company.name}: {e}")
                return []
            except httpx.RequestError as e:
                logger.error(f"Request error fetching {company.name}: {e}")
                return []

        jobs = data.get("jobs", [])
        return self._parse_jobs(jobs, company.id or 0)

    def _parse_jobs(
        self, jobs: list[dict[str, Any]], company_id: int
    ) -> list[RawPosting]:
        """Parse jobs from Greenhouse API response."""
        postings = []
        for job in jobs:
            location = job.get("location", {})
            location_name = (
                location.get("name") if isinstance(location, dict) else str(location)
            )

            posted_at = None
            if updated_at := job.get("updated_at"):
                try:
                    posted_at = datetime.fromisoformat(
                        updated_at.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            posting = RawPosting(
                company_id=company_id,
                title=job.get("title", ""),
                url=job.get("absolute_url", ""),
                description=self._clean_html(job.get("content", "")),
                location=location_name,
                posted_at=posted_at,
                source_id=str(job.get("id", "")),
                source_type="greenhouse",
            )
            postings.append(posting)

        return postings

    def _clean_html(self, html: str) -> str:
        """Strip HTML tags from content."""
        from bs4 import BeautifulSoup

        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(separator=" ", strip=True)
