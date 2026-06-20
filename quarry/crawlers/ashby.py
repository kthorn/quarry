# quarry/crawlers/ashby.py
import logging
from datetime import datetime
from typing import Any

import httpx

from quarry.crawlers.base import BaseCrawler, Crawl404Error
from quarry.http import get_client
from quarry.models import Company, RawPosting

logger = logging.getLogger(__name__)

# Ashby's public REST Posting API. This superseded the old
# `jobs.ashbyhq.com/api/non-user-graphql` `query { jobs(host: $host) {...} }`
# endpoint, whose `jobs` field was removed from the GraphQL Query type
# (returns `Cannot query field "jobs" on type "Query"`), silently yielding
# zero postings for every Ashby company. The posting-api is the documented
# public replacement (developers.ashbyhq.com/docs/public-job-posting-api).
POSTING_API_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


class AshbyCrawler(BaseCrawler):
    """Crawler for Ashby job boards using the public REST Posting API."""

    async def crawl(self, company: Company) -> list[RawPosting]:
        """Fetch jobs from Ashby's posting-api for the company's slug."""
        if not company.ats_slug:
            logger.warning(f"Company {company.name} has no ats_slug")
            return []

        url = POSTING_API_URL.format(slug=company.ats_slug)
        client = get_client()

        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise Crawl404Error(company.name, url) from e
            logger.error(f"HTTP error fetching {company.name}: {e}")
            return []
        except httpx.RequestError as e:
            logger.error(f"Request error fetching {company.name}: {e}")
            return []

        jobs_data = data.get("jobs", [])
        return self._parse_jobs(jobs_data, company.id or 0)

    def _parse_jobs(
        self, jobs: list[dict[str, Any]], company_id: int
    ) -> list[RawPosting]:
        """Parse jobs from the Ashby posting-api response.

        Response shape: ``{"apiVersion": "1", "jobs": [...]}`` where each job
        has ``id``, ``title``, ``location``, ``jobUrl``, ``descriptionPlain``,
        ``publishedAt`` (ISO 8601 with offset), etc.
        """
        postings = []
        for job in jobs:
            posted_at = None
            if posted_at_str := job.get("publishedAt"):
                try:
                    posted_at = datetime.fromisoformat(
                        posted_at_str.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            posting = RawPosting(
                company_id=company_id,
                title=job.get("title", ""),
                url=job.get("jobUrl", ""),
                description=job.get("descriptionPlain"),
                location=job.get("location", ""),
                posted_at=posted_at,
                source_id=job.get("id"),
                source_type="ashby",
            )
            postings.append(posting)

        return postings
