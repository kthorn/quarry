"""Scheduler: orchestrates crawl -> extract -> filter -> embed -> store pipeline.

Usage:
    python -m quarry.agent run-once
"""

import asyncio
import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from quarry.config import FiltersConfig, settings
from quarry.crawlers import get_crawler
from quarry.crawlers.base import Crawl404Error
from quarry.crawlers.jobspy_client import JobSpyClient
from quarry.models import Company, CrawlRun, JobPosting, ParseResult, RawPosting
from quarry.pipeline.embedder import (
    embed_posting,
    get_ideal_embedding,
    serialize_embedding,
    set_ideal_embedding,
)
from quarry.pipeline.extract import extract
from quarry.pipeline.filter import FILTER_STEPS
from quarry.store.db import Database

log = logging.getLogger(__name__)

CRAWL_LOG_COLUMNS = [
    "title",
    "source",
    "url",
    "location",
    "similarity_score",
    "status",
    "skip_reason",
]


def _ensure_ideal_embedding(db: Database, user_id: int = 1) -> None:
    """Ensure ideal role embedding exists in DB. Compute from config if missing."""
    ideal = get_ideal_embedding(db, user_id)
    if ideal is None:
        desc = settings.ideal_role_description
        if not desc:
            log.warning(
                "ideal_role_description is empty - similarity scoring will use zero vector"
            )
            return
        log.info("Computing ideal role embedding for user %d...", user_id)
        set_ideal_embedding(db, desc, user_id)
        log.info("Ideal role embedding stored for user %d", user_id)


def _crawl_company(company: Company) -> list[RawPosting]:
    """Crawl a single company's job postings (sync wrapper).

    Raises Crawl404Error if the ATS endpoint returns 404.
    Re-raises other exceptions so the caller can handle error tracking.
    """
    crawler = get_crawler(company)
    result = asyncio.run(crawler.crawl(company))
    return result


def _crawl_search_queries(db: Database, user_id: int = 1) -> list[RawPosting]:
    """Crawl job boards for all active search queries via JobSpy."""
    client = JobSpyClient()
    queries = db.get_active_search_queries(user_id=user_id)
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
        new_company = Company(name=name)
        new_company.id = db.insert_company(new_company, user_id=user_id)
        seen_companies[lower] = new_company
        return new_company

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
    company_name: str,
    filters_config: FiltersConfig | None,
    ideal_embedding: np.ndarray | None,
    user_id: int = 1,
) -> tuple[JobPosting | None, str, float, ParseResult | None]:
    """Process a single RawPosting through extract -> dedup -> filter -> embed.

    Returns (JobPosting or None, status string, similarity_score, ParseResult or None).

    Note: user_id is present for symmetry but not used inside the function;
    similarity writes happen in the caller via db.update_posting_similarity.
    """
    posting, parse_result = extract(raw)

    if db.posting_exists(posting.company_id, posting.title_hash):
        return None, "duplicate", 0.0, parse_result
    if db.posting_exists_by_url(posting.url):
        return None, "duplicate_url", 0.0, parse_result

    for step in FILTER_STEPS:
        config_section = step.get_config(filters_config)
        decision = step.check(raw, posting, parse_result, company_name, config_section)
        if not decision.passed:
            return None, decision.skip_reason or "filtered", 0.0, parse_result

    if ideal_embedding is None:
        similarity = 0.0
    else:
        embedding = embed_posting(raw)
        similarity = float(
            np.dot(embedding, ideal_embedding)
            / (np.linalg.norm(embedding) * np.linalg.norm(ideal_embedding) + 1e-9)
        )
        posting.embedding = serialize_embedding(embedding)

    return posting, "new", round(similarity, 4), parse_result


def _resolve_company_id(raw: RawPosting, db: Database) -> int:
    """Match a posting to an existing company, or create one if not found.

    Returns:
        company ID (always valid — creates a new company if needed)
    """
    company_name: str | None = None
    if " at " in raw.title:
        company_name = raw.title.split(" at ")[-1].strip()

    if company_name:
        companies = db.get_all_companies(active_only=False)
        for c in companies:
            if c.name.lower() == company_name.lower():
                assert c.id is not None
                return c.id

    if not company_name:
        company_name = "Unknown"

    new_company = Company(name=company_name)
    return db.insert_company(new_company)


def run_once(db: Database, user_id: int = 1) -> dict:
    """Run a single crawl cycle: crawl all companies + search queries, process, store.

    Returns a summary dict with counts. Also writes a CSV crawl log with every
    posting found and its similarity score.
    """
    _ensure_ideal_embedding(db, user_id)
    ideal_embedding = get_ideal_embedding(db, user_id)
    if ideal_embedding is not None:
        log.info("Ideal embedding loaded (dim=%d)", len(ideal_embedding))
    filters_config = settings.filters

    companies = db.get_all_companies(active_only=True)
    log.info("Phase: crawling %d active companies", len(companies))

    total_found = 0
    total_new = 0
    total_duplicates = 0
    total_filtered = 0
    companies_crawled = 0
    companies_errored = 0

    log_path = Path(
        f"crawl_log_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.csv"
    )
    log_file = open(log_path, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(log_file, fieldnames=CRAWL_LOG_COLUMNS)
    writer.writeheader()

    def _log_posting(
        raw: RawPosting,
        status: str,
        similarity: float,
        source: str,
        skip_reason: str | None = None,
    ) -> None:
        writer.writerow(
            {
                "title": raw.title,
                "source": source,
                "url": raw.url,
                "location": raw.location or "",
                "similarity_score": similarity,
                "status": status,
                "skip_reason": skip_reason or "",
            }
        )

    for company in companies:
        log.info(
            "[%d/%d] Crawling %s...",
            companies_crawled + companies_errored + 1,
            len(companies),
            company.name,
        )
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
            company_dupes = 0
            company_filtered = 0
            for raw in postings:
                job_posting, status, similarity, parse_result = _process_posting(
                    raw,
                    db,
                    company.name,
                    filters_config,
                    ideal_embedding,
                    user_id=user_id,
                )
                skip_reason = (
                    status
                    if status not in ("new", "duplicate", "duplicate_url")
                    else None
                )
                _log_posting(raw, status, similarity, company.name, skip_reason)
                if status == "new" and job_posting:
                    posting_id = db.insert_posting(job_posting, user_id=user_id)
                    if similarity and similarity > 0:
                        db.update_posting_similarity(
                            posting_id, round(similarity, 4), user_id=user_id
                        )
                    if parse_result:
                        for loc in parse_result.locations:
                            loc_id = db.get_or_create_location(loc)
                            db.link_posting_location(posting_id, loc_id)
                    company_new += 1
                    total_new += 1
                elif status.startswith("duplicate"):
                    company_dupes += 1
                    total_duplicates += 1
                else:
                    company_filtered += 1
                    total_filtered += 1

            run.postings_new = company_new
            run.status = "success"
            log.info(
                "[%d/%d] %s done: %d found, %d new, %d dupes, %d filtered",
                companies_crawled + companies_errored,
                len(companies),
                company.name,
                len(postings),
                company_new,
                company_dupes,
                company_filtered,
            )
        except Crawl404Error:
            log.warning("ATS 404 for %s — resetting ats_type to unknown", company.name)
            company.ats_type = "unknown"
            company.ats_slug = None
            db.update_company(company)
            companies_errored += 1
            run.status = "error"
            run.postings_found = 0
            run.postings_new = 0
        except Exception as e:
            log.error("Failed to crawl %s: %s", company.name, e)
            companies_errored += 1
            run.status = "error"
            run.postings_found = 0
            run.postings_new = 0

        db.insert_crawl_run(run)

    search_postings = _crawl_search_queries(db, user_id=user_id)
    total_found += len(search_postings)
    log.info("Phase: processing %d search query results", len(search_postings))

    for raw in search_postings:
        company_name = ""
        if " at " in raw.title:
            company_name = raw.title.split(" at ")[-1].strip()

        job_posting, status, similarity, parse_result = _process_posting(
            raw,
            db,
            company_name,
            filters_config,
            ideal_embedding,
            user_id=user_id,
        )
        skip_reason = (
            status if status not in ("new", "duplicate", "duplicate_url") else None
        )
        _log_posting(raw, status, similarity, "search", skip_reason)
        if status == "new" and job_posting:
            if not job_posting.company_id:
                job_posting.company_id = _resolve_company_id(raw, db)
            posting_id = db.insert_posting(job_posting, user_id=user_id)
            if similarity and similarity > 0:
                db.update_posting_similarity(
                    posting_id, round(similarity, 4), user_id=user_id
                )
            if parse_result:
                for loc in parse_result.locations:
                    loc_id = db.get_or_create_location(loc)
                    db.link_posting_location(posting_id, loc_id)
            total_new += 1
        elif status.startswith("duplicate"):
            total_duplicates += 1
        else:
            total_filtered += 1

    log_file.close()
    summary = {
        "companies_crawled": companies_crawled,
        "companies_errored": companies_errored,
        "total_found": total_found,
        "total_new": total_new,
        "total_duplicates": total_duplicates,
        "total_filtered": total_filtered,
        "crawl_log": str(log_path),
    }
    log.info("Run complete: %s", summary)
    return summary
