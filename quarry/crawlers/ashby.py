# quarry/crawlers/ashby.py
import logging
from datetime import datetime
from typing import Any

import httpx

from quarry.crawlers.base import BaseCrawler
from quarry.models import Company, RawPosting

logger = logging.getLogger(__name__)


GRAPHQL_QUERY = """
query($host: String!) {
  jobs(host: $host) {
    id
    title
    location
    absoluteUrl
    descriptionPlain
    postedAt
  }
}
"""


class AshbyCrawler(BaseCrawler):
    """Crawler for Ashby job boards using GraphQL."""

    BASE_URL = "https://jobs.ashbyhq.com/api/non-user-graphql"

    async def crawl(self, company: Company) -> list[RawPosting]:
        """Fetch jobs from Ashby GraphQL API."""
        if not company.ats_slug:
            logger.warning(f"Company {company.name} has no ats_slug")
            return []

        host = company.ats_slug

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(
                    self.BASE_URL,
                    json={
                        "query": GRAPHQL_QUERY,
                        "variables": {"host": host},
                    },
                )
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error fetching {company.name}: {e}")
                return []
            except httpx.RequestError as e:
                logger.error(f"Request error fetching {company.name}: {e}")
                return []

        jobs_data = data.get("data", {}).get("jobs", [])
        return self._parse_jobs(jobs_data, company.id or 0)

    def _parse_jobs(
        self, jobs: list[dict[str, Any]], company_id: int
    ) -> list[RawPosting]:
        """Parse jobs from Ashby GraphQL response."""
        postings = []
        for job in jobs:
            posted_at = None
            if posted_at_str := job.get("postedAt"):
                try:
                    posted_at = datetime.fromisoformat(
                        posted_at_str.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            location = job.get("location", "")
            is_remote = None
            if location and "remote" in location.lower():
                is_remote = True

            posting = RawPosting(
                company_id=company_id,
                title=job.get("title", ""),
                url=job.get("absoluteUrl", ""),
                description=job.get("descriptionPlain"),
                location=location,
                remote=is_remote,
                posted_at=posted_at,
                source_id=job.get("id"),
                source_type="ashby",
            )
            postings.append(posting)

        return postings
