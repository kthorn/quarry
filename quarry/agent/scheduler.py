"""Scheduler: orchestrates crawl -> extract -> embed -> filter -> store pipeline.

Usage:
    python -m quarry.agent run-once
"""

import asyncio
import logging
from datetime import datetime, timezone

import numpy as np

from quarry.config import settings
from quarry.crawlers import get_crawler
from quarry.crawlers.jobspy_client import JobSpyClient
from quarry.models import Company, CrawlRun, JobPosting, RawPosting
from quarry.pipeline.embedder import (
    embed_posting,
    get_ideal_embedding,
    serialize_embedding,
    set_ideal_embedding,
)
from quarry.pipeline.extract import extract
from quarry.pipeline.filter import apply_keyword_blocklist, filter_posting
from quarry.store.db import Database

log = logging.getLogger(__name__)


def _ensure_ideal_embedding(db: Database) -> None:
    """Ensure ideal role embedding exists in DB. Compute from config if missing."""
    ideal = get_ideal_embedding(db)
    if ideal is None:
        desc = settings.ideal_role_description
        if not desc:
            log.warning(
                "ideal_role_description is empty - similarity scoring will use zero vector"
            )
            return
        set_ideal_embedding(db, desc)
        log.info("Computed and stored ideal role embedding")


def _crawl_company(company: Company) -> list[RawPosting]:
    """Crawl a single company's job postings (sync wrapper).

    Raises: Re-raises exceptions so the caller can handle error tracking.
    """
    crawler = get_crawler(company)
    result = asyncio.run(crawler.crawl(company))
    return result


def _crawl_search_queries(db: Database) -> list[RawPosting]:
    """Crawl job boards for all active search queries via JobSpy."""
    client = JobSpyClient()
    queries = db.get_active_search_queries()
    if not queries:
        log.info("No active search queries found")
        return []

    all_postings: list[RawPosting] = []

    seen_companies: dict[str, Company] = {}
    companies = db.get_all_companies(active_only=False)
    for c in companies:
        seen_companies[c.name.lower()] = c

    def company_resolver(name: str) -> Company:
        lower = name.lower()
        if lower in seen_companies:
            return seen_companies[lower]
        return Company(name=name)

    for q in queries:
        log.info("Searching: %s", q.query_text)
        try:
            postings = client.fetch(q.query_text, company_resolver=company_resolver)
            log.info("Found %d results for '%s'", len(postings), q.query_text)
            all_postings.extend(postings)
        except Exception as e:
            log.error("JobSpy search failed for '%s': %s", q.query_text, e)

    return all_postings


def _process_posting(
    raw: RawPosting,
    db: Database,
    blocklist: list[str],
    ideal_embedding: np.ndarray | None,
) -> tuple[JobPosting | None, str]:
    """Process a single RawPosting through extract -> dedup -> embed -> filter.

    Returns (JobPosting or None, status string: "new", "duplicate", "duplicate_url", "blocklist", "filtered").
    """
    posting = extract(raw)

    if db.posting_exists(posting.company_id, posting.title_hash):
        return None, "duplicate"
    if db.posting_exists_by_url(posting.url):
        return None, "duplicate_url"

    if not apply_keyword_blocklist(raw, blocklist):
        return None, "blocklist"

    if ideal_embedding is None:
        similarity = 0.0
    else:
        result = filter_posting(raw, ideal_embedding, blocklist=blocklist)
        similarity = result.similarity_score or 0.0
        if not result.passed:
            return None, result.skip_reason or "filtered"

    posting.similarity_score = similarity
    if ideal_embedding is not None:
        emb = embed_posting(raw)
        posting.embedding = serialize_embedding(emb)

    return posting, "new"


def _resolve_company_id(raw: RawPosting, db: Database) -> int | None:
    """Try to match a JobSpy posting to an existing company by name.

    Returns company ID if found, None otherwise.
    """
    title = raw.title
    if " at " in title:
        company_name = title.split(" at ")[-1].strip()
        companies = db.get_all_companies(active_only=False)
        for c in companies:
            if c.name.lower() == company_name.lower():
                return c.id
    return None


def run_once(db: Database) -> dict:
    """Run a single crawl cycle: crawl all companies + search queries, process, store.

    Returns a summary dict with counts.
    """
    _ensure_ideal_embedding(db)
    ideal_embedding = get_ideal_embedding(db)
    blocklist: list[str] = getattr(settings, "keyword_blocklist", []) or []

    companies = db.get_all_companies(active_only=True)
    log.info("Crawling %d active companies", len(companies))

    total_found = 0
    total_new = 0
    total_duplicates = 0
    total_filtered = 0
    companies_crawled = 0
    companies_errored = 0

    for company in companies:
        run = CrawlRun(
            company_id=company.id,
            started_at=datetime.now(timezone.utc),
            status="running",
        )

        try:
            postings = _crawl_company(company)
            total_found += len(postings)
            companies_crawled += 1

            run.completed_at = datetime.now(timezone.utc)
            run.postings_found = len(postings)

            company_new = 0
            for raw in postings:
                job_posting, status = _process_posting(
                    raw, db, blocklist, ideal_embedding
                )
                if status == "new" and job_posting:
                    db.insert_posting(job_posting)
                    company_new += 1
                    total_new += 1
                elif status.startswith("duplicate"):
                    total_duplicates += 1
                else:
                    total_filtered += 1

            run.postings_new = company_new
            run.status = "success"
        except Exception as e:
            log.error("Failed to crawl %s: %s", company.name, e)
            companies_errored += 1
            run.status = "error"
            run.postings_found = 0
            run.postings_new = 0

        db.insert_crawl_run(run)

    search_postings = _crawl_search_queries(db)
    total_found += len(search_postings)

    for raw in search_postings:
        job_posting, status = _process_posting(raw, db, blocklist, ideal_embedding)
        if status == "new" and job_posting:
            if not job_posting.company_id:
                resolved = _resolve_company_id(raw, db)
                if resolved is not None:
                    job_posting.company_id = resolved
            db.insert_posting(job_posting)
            total_new += 1
        elif status.startswith("duplicate"):
            total_duplicates += 1
        else:
            total_filtered += 1

    summary = {
        "companies_crawled": companies_crawled,
        "companies_errored": companies_errored,
        "total_found": total_found,
        "total_new": total_new,
        "total_duplicates": total_duplicates,
        "total_filtered": total_filtered,
    }
    log.info("Run complete: %s", summary)
    return summary
