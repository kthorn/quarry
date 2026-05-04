# quarry/crawlers/jobspy_client.py
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

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


@dataclass
class JobSpyCompanyHints:
    """Per-row company hints extracted from JobSpy metadata."""

    domain_hint: str | None
    ats_type_hint: str | None
    ats_slug_hint: str | None
    greenhouse_subdomain: str | None = (
        None  # "boards" or "job-boards" for greenhouse URLs
    )

    def build_careers_url(self) -> str | None:
        """Build canonical careers URL from ATS hints.

        Preserves the subdomain detected from the job URL. Greenhouse boards
        use either boards.greenhouse.io or job-boards.greenhouse.io — they
        301-redirect to each other depending on company, so we mirror the
        detection pattern rather than guessing.
        """
        if self.ats_type_hint == "greenhouse" and self.ats_slug_hint:
            sub = self.greenhouse_subdomain or "boards"
            return f"https://{sub}.greenhouse.io/{self.ats_slug_hint}"
        elif self.ats_type_hint == "lever" and self.ats_slug_hint:
            return f"https://jobs.lever.co/{self.ats_slug_hint}"
        elif self.ats_type_hint == "ashby" and self.ats_slug_hint:
            return f"https://jobs.ashbyhq.com/{self.ats_slug_hint}"
        return None


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
        self.location = location or ""

    def fetch(
        self,
        query: str,
        company_resolver: Callable[[str, JobSpyCompanyHints], Company] | None = None,
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
        company_resolver: Callable[[str, JobSpyCompanyHints], Company],
    ) -> list[RawPosting]:
        """Convert JobSpy DataFrame to RawPosting list."""
        postings = []
        seen_companies: dict[str, Company] = {}

        for _, row in df.iterrows():
            company_name = self._safe_str(row.get("company"), "Unknown")
            # NOTE: JobSpy column is 'site', not 'site_name' — verified empirically
            site = self._safe_str(row.get("site"), "indeed")
            job_url_direct = self._safe_str(row.get("job_url_direct"), "")
            company_url_direct = self._safe_str(row.get("company_url_direct"), "")

            source_type = SITE_NAME_TO_SOURCE_TYPE.get(site.lower(), site.lower())

            ats_type, ats_slug, ghs = self._detect_ats_from_url(job_url_direct)

            hints = JobSpyCompanyHints(
                domain_hint=self._extract_domain(company_url_direct) or None,
                ats_type_hint=ats_type,
                ats_slug_hint=ats_slug,
                greenhouse_subdomain=ghs,
            )

            if company_name not in seen_companies:
                company = company_resolver(company_name, hints)
                seen_companies[company_name] = company

            company = seen_companies[company_name]
            company_id = company.id if company and company.id else 0

            desc_raw = row.get("description")
            loc_raw = row.get("location")

            posting = RawPosting(
                company_id=company_id,
                title=self._safe_str(row.get("title"), "Unknown"),
                url=self._safe_str(row.get("url"), ""),
                description=self._safe_str(desc_raw)
                if desc_raw is not None and pd.notna(desc_raw)
                else None,
                location=self._safe_str(loc_raw)
                if loc_raw is not None and pd.notna(loc_raw)
                else None,
                posted_at=row.get("date_posted"),
                # NOTE: JobSpy column is 'id', not 'job_id' — verified empirically
                source_id=self._safe_str(row.get("id"), ""),
                source_type=str(source_type),
            )
            postings.append(posting)

        return postings

    @staticmethod
    def _safe_str(value, default: str = "") -> str:
        """Convert a pandas value to string, treating NaN/None as default."""
        if value is None or pd.isna(value):
            return default
        s = str(value).strip()
        return s if s else default

    def _default_company_resolver(
        self, company_name: str, hints: JobSpyCompanyHints | None = None
    ) -> Company:
        """Default resolver returns Company with no ID."""
        return Company(name=company_name, id=None)

    # NOTE: _safe_str already exists above — do not redefine.
    # The tests in test_jobspy_client.py serve as regression coverage.

    @staticmethod
    def _extract_domain(url: str | None) -> str | None:
        """Extract clean domain from a URL, or None if invalid."""
        if not url:
            return None
        parsed = urlparse(url)
        if parsed.hostname:
            return parsed.hostname.lower().removeprefix("www.")
        return None

    @staticmethod
    def _detect_ats_from_url(
        url: str | None,
    ) -> tuple[str | None, str | None, str | None]:
        """Detect ATS type, slug, and greenhouse subdomain from a direct job board URL.

        Returns (ats_type, ats_slug, greenhouse_subdomain) or (None, None, None).
        """
        if not url:
            return None, None, None
        import re

        patterns = [
            (r"job-boards\.greenhouse\.io/([^/]+)", "greenhouse", "job-boards"),
            (r"boards\.greenhouse\.io/([^/]+)", "greenhouse", "boards"),
            (r"boards-api\.greenhouse\.io/v1/boards/([^/]+)", "greenhouse", "boards"),
            (r"jobs\.lever\.co/([^/]+)", "lever", None),
            (r"jobs\.ashbyhq\.com/([^/]+)", "ashby", None),
            (r"careers\.ashbyhq\.com/([^/]+)", "ashby", None),
        ]
        for pattern, ats_type, subdomain in patterns:
            match = re.search(pattern, url)
            if match:
                return ats_type, match.group(1), subdomain
        return None, None, None
