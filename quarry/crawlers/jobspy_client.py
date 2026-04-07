# quarry/crawlers/jobspy_client.py
from collections.abc import Callable

import pandas as pd
from jobspy import scrape_jobs

from quarry.config import settings
from quarry.models import Company, RawPosting


SITE_NAME_TO_SOURCE_TYPE: dict[str, str] = {
    "indeed": "indeed",
    "glassdoor": "glassdoor",
    "google": "google_jobs",
    "zip_recruiter": "zip_recruiter",
    "linkedin": "linkedin",
}


class JobSpyClient:
    """Thin wrapper around python-jobspy scrape_jobs()."""

    def __init__(
        self,
        sites: list[str] | None = None,
        results_wanted: int | None = None,
        hours_old: int | None = None,
        location: str | None = None,
    ):
        self.sites = sites or settings.jobspy_sites
        self.results_wanted = results_wanted or settings.jobspy_results_wanted
        self.hours_old = hours_old or settings.jobspy_hours_old
        self.location = location or settings.jobspy_location

    def fetch(
        self,
        query: str,
        company_resolver: Callable[[str], Company] | None = None,
    ) -> list[RawPosting]:
        """Fetch job postings from JobSpy sources.

        Args:
            query: Search query (e.g., "software engineer")
            company_resolver: Optional callable(company_name: str) -> Company
                that looks up or creates a company and returns it with company_id set.
                If not provided, company_id will be 0.

        Returns:
            List of RawPosting objects
        """
        if company_resolver is None:
            company_resolver = self._default_company_resolver

        df = scrape_jobs(
            search_term=query,
            sites=self.sites,
            results_wanted=self.results_wanted,
            hours_old=self.hours_old,
            location=self.location,
        )

        if df.empty:
            return []

        return self._convert_dataframe(df, company_resolver)

    def _convert_dataframe(
        self,
        df: pd.DataFrame,
        company_resolver: Callable[[str], Company],
    ) -> list[RawPosting]:
        """Convert JobSpy DataFrame to RawPosting list."""
        postings = []
        seen_companies: dict[str, Company] = {}

        for _, row in df.iterrows():
            company_name = str(row.get("company", "Unknown"))
            site_name = str(row.get("site_name", "indeed"))

            source_type = SITE_NAME_TO_SOURCE_TYPE.get(
                site_name.lower(), site_name.lower()
            )

            if company_name not in seen_companies:
                company = company_resolver(company_name)
                seen_companies[company_name] = company

            company = seen_companies[company_name]
            company_id = company.id if company and company.id else 0

            posting = RawPosting(
                company_id=company_id,
                title=str(row.get("title", "Unknown")),
                url=str(row.get("url", "")),
                description=str(row.get("description"))
                if row.get("description")
                else None,
                location=str(row.get("location")) if row.get("location") else None,
                remote=self._parse_remote(row),
                posted_at=row.get("date_posted"),
                source_id=str(row.get("job_id", "")),
                source_type=str(source_type),
            )
            postings.append(posting)

        return postings

    def _parse_remote(self, row: pd.Series) -> bool | None:
        """Parse remote flag from job data."""
        job_type = row.get("job_type", "")
        if job_type and "remote" in str(job_type).lower():
            return True
        return None

    def _default_company_resolver(self, company_name: str) -> Company:
        """Default resolver returns Company with no ID."""
        return Company(name=company_name, id=None)
