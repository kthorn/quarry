# M6 + M7 Minimal: Scheduler (run-once) + Digest (file output)

**Status:** Refined

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get an end-to-end pipeline you can run with a single command that crawls companies, extracts/embeds/filters postings, and writes a ranked digest file.

**Architecture:** Two new modules: `quarry/agent/scheduler.py` orchestrates crawl → extract → embed → filter → store for all active companies, and `quarry/digest/digest.py` reads scored postings from DB and writes a plain-text digest file. The scheduler and digest are separate CLI commands (`python -m quarry.agent run-once` and `python -m quarry.digest`); you can chain them in a shell one-liner. No APScheduler cron. No email/Slack — just file output. Seed data is loaded via a `seed` CLI command.

**Tech Stack:** Python 3.11, httpx (already in deps), click (already in deps), asyncio (stdlib), sentence-transformers (already in deps)

**Note:** Add `digest_*.txt` to `.gitignore` so digest output files aren't accidentally committed.

---

## File Structure

| File | Purpose |
|------|---------|
| `quarry/agent/__init__.py` | Package init |
| `quarry/agent/tools.py` | `seed()` command — loads companies/queries from YAML into DB |
| `quarry/agent/scheduler.py` | `run_once()` — crawl all companies, extract, embed, filter, store |
| `quarry/agent/__main__.py` | CLI: `python -m quarry.agent run-once` |
| `quarry/digest/__init__.py` | Package init |
| `quarry/digest/digest.py` | `build_digest()` + `write_digest()` — read new postings, format, write file |
| `quarry/digest/__main__.py` | CLI: `python -m quarry.digest` |
| `tests/test_scheduler.py` | Tests for run_once pipeline with mocked crawlers |
| `tests/test_seed.py` | Tests for seed command |
| `tests/test_digest.py` | Tests for digest build + format |

---

## Task 1: Seed loading command

**Files:**
- Create: `quarry/agent/__init__.py`
- Create: `quarry/agent/tools.py`
- Test: `tests/test_seed.py`

> **Note:** `seed_data.yaml` is being created separately. This task only covers the `load_seed_data()` and `seed()` functions that read from it.

- [ ] **Step 1: Write test for seed loading**

```python
# tests/test_seed.py
import pytest
import yaml
from pathlib import Path

from quarry.store.db import Database, init_db
from quarry.agent.tools import load_seed_data, seed


@pytest.fixture
def db(tmp_path):
    return init_db(str(tmp_path / "test.db"))


@pytest.fixture
def seed_file(tmp_path):
    """Create a minimal seed file for testing."""
    data = {
        "companies": [
            {"name": "TestCorp", "ats_type": "greenhouse", "ats_slug": "testcorp", "domain": "testcorp.com"},
        ],
        "search_queries": [
            {"query_text": "People Analytics Manager", "added_reason": "Direct match"},
        ],
    }
    path = tmp_path / "seed_data.yaml"
    path.write_text(yaml.dump(data))
    return str(path)


class TestLoadSeedData:
    def test_load_companies_from_yaml(self, db, seed_file):
        companies, queries = load_seed_data(seed_file)
        assert len(companies) == 1
        assert companies[0].name == "TestCorp"
        assert companies[0].ats_type == "greenhouse"

    def test_load_queries_from_yaml(self, db, seed_file):
        companies, queries = load_seed_data(seed_file)
        assert len(queries) == 1
        assert queries[0].query_text == "People Analytics Manager"

    def test_load_raises_for_missing_file(self, db):
        with pytest.raises(FileNotFoundError):
            load_seed_data("/nonexistent/path.yaml")


class TestSeed:
    def test_seed_inserts_into_db(self, db, seed_file):
        seed(db, seed_file)
        companies = db.get_all_companies(active_only=False)
        assert len(companies) == 1
        assert companies[0].name == "TestCorp"

    def test_seed_is_idempotent(self, db, seed_file):
        seed(db, seed_file)
        seed(db, seed_file)
        companies = db.get_all_companies(active_only=False)
        assert len(companies) == 1

    def test_seed_inserts_queries(self, db, seed_file):
        seed(db, seed_file)
        queries = db.get_active_search_queries()
        assert len(queries) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/home/kurtt/job-search pytest tests/test_seed.py -v`
Expected: FAIL — `quarry.agent.tools` does not exist yet.

- [ ] **Step 3: Create `quarry/agent/__init__.py`**

```python
"""Quarry agent: scheduler, tools, and strategy reflection."""
```

- [ ] **Step 4: Create `quarry/agent/tools.py` with `load_seed_data()`**

```python
"""Agent tools: seed data loading and strategy utilities."""

import logging
from pathlib import Path

import yaml

from quarry.config import settings
from quarry.models import Company, SearchQuery
from quarry.store.db import Database

log = logging.getLogger(__name__)


def load_seed_data(seed_path: str | None = None) -> tuple[list[Company], list[SearchQuery]]:
    """Load companies and search queries from a YAML seed file.

    Args:
        seed_path: Path to seed_data.yaml. Defaults to config seed_file.

    Returns:
        Tuple of (companies, search_queries) parsed from the YAML file.
    """
    path = Path(seed_path or settings.seed_file)
    if not path.exists():
        raise FileNotFoundError(f"Seed file not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    companies = []
    for c in data.get("companies", []):
        companies.append(Company(
            name=c["name"],
            domain=c.get("domain"),
            careers_url=c.get("careers_url"),
            ats_type=c.get("ats_type", "unknown"),
            ats_slug=c.get("ats_slug"),
            active=c.get("active", True),
            crawl_priority=c.get("crawl_priority", 5),
            notes=c.get("notes"),
            added_by="seed",
            added_reason=c.get("added_reason"),
        ))

    queries = []
    for q in data.get("search_queries", []):
        queries.append(SearchQuery(
            query_text=q["query_text"],
            site=q.get("site"),
            active=q.get("active", True),
            added_by="seed",
            added_reason=q.get("added_reason"),
        ))

    return companies, queries


def seed(db: Database, seed_path: str | None = None) -> None:
    """Load seed data into the database.

    Idempotent: skips companies/queries that already exist (by name/query_text).
    """
    companies, queries = load_seed_data(seed_path)

    existing_companies = {c.name.lower() for c in db.get_all_companies(active_only=False)}
    for company in companies:
        if company.name.lower() in existing_companies:
            log.info("Skipping existing company: %s", company.name)
            continue
        db.insert_company(company)
        log.info("Seeded company: %s", company.name)

    existing_queries = {q.query_text for q in db.get_active_search_queries()}
    for query in queries:
        if query.query_text in existing_queries:
            log.info("Skipping existing query: %s", query.query_text)
            continue
        # Note: only dedupes against active queries; inactive duplicates
        # may be re-seeded. Acceptable for MVP — can add get_all_search_queries() later.
        db.insert_search_query(query)
        log.info("Seeded query: %s", query.query_text)

    log.info("Seed complete: %d companies, %d queries", len(companies), len(queries))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `PYTHONPATH=/home/kurtt/job-search pytest tests/test_seed.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add quarry/agent/__init__.py quarry/agent/tools.py tests/test_seed.py
git commit -m "feat: add seed loading command"
```

---

## Task 2: Scheduler run_once pipeline

**Files:**
- Create: `quarry/agent/scheduler.py`
- Create: `quarry/agent/__main__.py`
- Test: `tests/test_scheduler.py`

This is the core end-to-end pipeline: iterate over companies → crawl → extract → embed → filter → store. Only `run-once` subcommand, no cron.

- [ ] **Step 1: Write test for run_once with mocked crawlers**

```python
# tests/test_scheduler.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from quarry.models import Company, RawPosting, CrawlRun, JobPosting
from quarry.store.db import Database, init_db
from quarry.agent.scheduler import run_once


@pytest.fixture
def db(tmp_path):
    return init_db(str(tmp_path / "test.db"))


@pytest.fixture
def seeded_db(db):
    company = Company(name="TestCorp", ats_type="greenhouse", ats_slug="testcorp")
    db.insert_company(company)
    return db


def _make_raw_posting(company_id=1, title="Senior Data Analyst", url="https://example.com/job/1"):
    return RawPosting(
        company_id=company_id,
        title=title,
        url=url,
        description="Analyze people data and build dashboards",
        location="Remote, US",
        source_type="greenhouse",
    )


class TestRunOnce:
    def test_run_once_processes_companies(self, seeded_db):
        mock_postings = [_make_raw_posting()]

        with patch("quarry.agent.scheduler._crawl_company") as mock_crawl, \
             patch("quarry.agent.scheduler._crawl_search_queries") as mock_search:
            mock_crawl.return_value = mock_postings
            mock_search.return_value = []

            from quarry.pipeline.embedder import set_ideal_embedding
            set_ideal_embedding(seeded_db, "Senior people analytics leader role")

            summary = run_once(seeded_db)

            assert summary["companies_crawled"] >= 1
            assert summary["total_found"] >= 1
            postings = seeded_db.get_postings()
            assert len(postings) >= 1
            assert postings[0].similarity_score is not None

    def test_run_once_skips_duplicates(self, seeded_db):
        mock_postings = [_make_raw_posting()]

        with patch("quarry.agent.scheduler._crawl_company") as mock_crawl, \
             patch("quarry.agent.scheduler._crawl_search_queries") as mock_search:
            mock_crawl.return_value = mock_postings
            mock_search.return_value = []

            from quarry.pipeline.embedder import set_ideal_embedding
            set_ideal_embedding(seeded_db, "Senior people analytics leader role")

            run_once(seeded_db)

            mock_crawl.return_value = [_make_raw_posting()]
            summary = run_once(seeded_db)
            assert summary["total_new"] == 0

    def test_run_once_logs_crawl_run(self, seeded_db):
        mock_postings = [_make_raw_posting()]

        with patch("quarry.agent.scheduler._crawl_company") as mock_crawl, \
             patch("quarry.agent.scheduler._crawl_search_queries") as mock_search:
            mock_crawl.return_value = mock_postings
            mock_search.return_value = []

            from quarry.pipeline.embedder import set_ideal_embedding
            set_ideal_embedding(seeded_db, "Senior people analytics leader role")

            run_once(seeded_db)

            runs = seeded_db.execute("SELECT * FROM crawl_runs")
            assert len(runs) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=/home/kurtt/job-search pytest tests/test_scheduler.py -v`
Expected: FAIL — `quarry.agent.scheduler` does not exist yet.

- [ ] **Step 3: Create `quarry/agent/scheduler.py`**

```python
"""Scheduler: orchestrates crawl → extract → embed → filter → store pipeline.

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
from quarry.models import CrawlRun, Company, JobPosting, RawPosting
from quarry.pipeline.embedder import embed_posting, get_ideal_embedding, set_ideal_embedding, serialize_embedding
from quarry.pipeline.extract import extract
from quarry.pipeline.filter import filter_posting, apply_keyword_blocklist
from quarry.store.db import Database

log = logging.getLogger(__name__)


def _ensure_ideal_embedding(db: Database) -> None:
    """Ensure ideal role embedding exists in DB. Compute from config if missing."""
    ideal = get_ideal_embedding(db)
    if ideal is None:
        desc = settings.ideal_role_description
        if not desc:
            log.warning("ideal_role_description is empty — similarity scoring will use zero vector")
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


def _process_posting(raw: RawPosting, db: Database, blocklist: list[str], ideal_embedding: np.ndarray | None) -> tuple[JobPosting | None, str]:
    """Process a single RawPosting through extract → dedup → embed → filter.

    Args:
        raw: Raw posting from crawler.
        db: Database instance.
        blocklist: Keyword blocklist phrases.
        ideal_embedding: Pre-computed ideal role embedding (avoids repeated DB lookups).

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
                job_posting, status = _process_posting(raw, db, blocklist, ideal_embedding)
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
            # Resolve company_id for JobSpy results where company_resolver
            # returned a Company with id=None (unmatched company name)
            if job_posting.company_id in (0, None):
                job_posting.company_id = _resolve_company_id(raw, db)
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
```

- [ ] **Step 4: Create `quarry/agent/__main__.py`**

```python
"""Agent CLI entrypoint.

Usage:
    python -m quarry.agent run-once
    python -m quarry.agent seed
"""

import click

from quarry.config import settings
from quarry.store.db import get_db


@click.group()
def cli():
    """Quarry agent commands."""
    pass


@cli.command()
def run_once():
    """Run a single crawl cycle."""
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    from quarry.agent.scheduler import run_once as do_run

    db = get_db()
    summary = do_run(db)
    click.echo(f"Crawl complete: {summary}")


@cli.command()
def seed():
    """Load seed data into the database."""
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    from quarry.agent.tools import seed as do_seed

    db = get_db()
    do_seed(db)
    click.echo("Seed data loaded.")


if __name__ == "__main__":
    cli()
```

- [ ] **Step 5: Run tests**

Run: `PYTHONPATH=/home/kurtt/job-search pytest tests/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 6: Run all tests to check for regressions**

Run: `PYTHONPATH=/home/kurtt/job-search pytest tests/ -v --ignore=tests/test_jobspy_integration.py`
Expected: All pass

- [ ] **Step 7: Update AGENTS.md to reference new commands**

Add the `seed` and `--run-once` commands to AGENTS.md if they differ from what's there. Check current content first.

- [ ] **Step 8: Commit**

```bash
git add quarry/agent/scheduler.py quarry/agent/__main__.py quarry/agent/__init__.py tests/test_scheduler.py
git commit -m "feat: add scheduler run_once pipeline (M6 minimal)"
```

---

## Task 3: Digest file output

**Files:**
- Create: `quarry/digest/__init__.py`
- Create: `quarry/digest/digest.py`
- Create: `quarry/digest/__main__.py`
- Test: `tests/test_digest.py`

Read new postings from DB, sort by similarity, format as plain text, write to file.

- [ ] **Step 1: Add `get_recent_postings()` to `quarry/store/db.py`**

The digest needs to query postings that are `new` and haven't been included in a digest yet. We'll use the `status` field — when the user runs `python -m quarry.digest --mark-seen`, postings are marked as `seen`. This is an opt-in flag so users can preview the digest before committing.

Add this method to `Database` class in `quarry/store/db.py`:

```python
def get_recent_postings(self, limit: int = 100, status: str = "new") -> list[models.JobPosting]:
    """Get recent postings ordered by similarity_score descending.

    Args:
        limit: Maximum number of postings to return.
        status: Filter by posting status.

    Returns:
        List of JobPosting objects sorted by similarity_score descending.
    """
    sql = """
        SELECT * FROM job_postings
        WHERE status = ?
        ORDER BY similarity_score DESC
        LIMIT ?
    """
    rows = self.execute(sql, (status, limit))
    return [models.JobPosting(**dict(row)) for row in rows]

def mark_postings_seen(self, posting_ids: list[int]) -> None:
    """Mark postings as seen (included in digest).

    Args:
        posting_ids: List of posting IDs to mark as seen.
    """
    if not posting_ids:
        return
    placeholders = ",".join("?" * len(posting_ids))
    sql = f"UPDATE job_postings SET status = 'seen' WHERE id IN ({placeholders})"
    self.execute(sql, tuple(posting_ids))

def get_company_name(self, company_id: int) -> str | None:
    """Get company name by ID.

    Args:
        company_id: Company ID to look up.

    Returns:
        Company name or None if not found.
    """
    sql = "SELECT name FROM companies WHERE id = ?"
    rows = self.execute(sql, (company_id,))
    return rows[0]["name"] if rows else None
```

- [ ] **Step 2: Write test for digest**

```python
# tests/test_digest.py
import pytest
from pathlib import Path

from quarry.models import Company, JobPosting
from quarry.store.db import Database, init_db
from quarry.digest.digest import build_digest, format_digest, write_digest


@pytest.fixture
def db(tmp_path):
    return init_db(str(tmp_path / "test.db"))


@pytest.fixture
def db_with_postings(db):
    company = Company(name="TestCorp", ats_type="greenhouse", ats_slug="testcorp")
    cid = db.insert_company(company)

    for i in range(3):
        posting = JobPosting(
            company_id=cid,
            title=f"Senior Analyst {i}",
            title_hash=f"hash_{i}",
            url=f"https://example.com/job/{i}",
            description=f"Great analytics role {i}",
            location="Remote, US",
            remote=True,
            similarity_score=0.8 - i * 0.1,
            source_type="greenhouse",
        )
        db.insert_posting(posting)
    return db


class TestBuildDigest:
    def test_returns_recent_postings(self, db_with_postings):
        entries = build_digest(db_with_postings, limit=10)
        assert len(entries) == 3

    def test_sorted_by_similarity(self, db_with_postings):
        entries = build_digest(db_with_postings, limit=10)
        scores = [e["similarity_score"] for e in entries]
        assert scores == sorted(scores, reverse=True)

    def test_marks_postings_seen(self, db_with_postings):
        entries = build_digest(db_with_postings, limit=10)
        posting_ids = [e["id"] for e in entries]
        db_with_postings.mark_postings_seen(posting_ids)

        new_entries = build_digest(db_with_postings, limit=10)
        assert len(new_entries) == 0


class TestFormatDigest:
    def test_formats_as_plain_text(self, db_with_postings):
        entries = build_digest(db_with_postings, limit=10)
        text = format_digest(entries)
        assert "TestCorp" in text
        assert "Senior Analyst" in text
        assert "similarity" in text.lower() or "score" in text.lower()

    def test_empty_digest(self, db_with_postings):
        text = format_digest([])
        assert "no new postings" in text.lower() or text.strip() == ""


class TestWriteDigest:
    def test_writes_to_file(self, db_with_postings, tmp_path):
        entries = build_digest(db_with_postings, limit=10)
        output_path = tmp_path / "digest.txt"
        write_digest(entries, str(output_path))
        assert output_path.exists()
        content = output_path.read_text()
        assert "Senior Analyst" in content
```

- [ ] **Step 3: Run test to verify it fails**

Run: `PYTHONPATH=/home/kurtt/job-search pytest tests/test_digest.py -v`
Expected: FAIL — `quarry.digest.digest` does not exist yet.

- [ ] **Step 4: Create `quarry/digest/__init__.py`**

```python
"""Quarry digest: daily ranked job postings output."""
```

- [ ] **Step 5: Create `quarry/digest/digest.py`**

```python
"""Build and write digest of new job postings.

Reads new postings from DB, sorts by similarity, formats as plain text,
and writes to a file. Marks included postings as 'seen'.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

from quarry.config import settings
from quarry.store.db import Database

log = logging.getLogger(__name__)


def build_digest(db: Database, limit: int | None = None) -> list[dict]:
    """Fetch new postings sorted by similarity score.

    Args:
        db: Database instance.
        limit: Maximum postings to include. Defaults to config digest_top_n.

    Returns:
        List of dicts with posting data, sorted by similarity_score descending.
    """
    limit = limit or settings.digest_top_n
    postings = db.get_recent_postings(limit=limit, status="new")
    entries = []
    for p in postings:
        company_name = db.get_company_name(p.company_id) or "Unknown"
        entries.append({
            "id": p.id,
            "company_name": company_name,
            "title": p.title,
            "url": p.url,
            "similarity_score": p.similarity_score or 0.0,
            "location": p.location or "N/A",
            "remote": p.remote,
        })
    return entries


def format_digest(entries: list[dict]) -> str:
    """Format digest entries as plain text.

    Args:
        entries: List of posting dicts from build_digest.

    Returns:
        Formatted plain text digest string.
    """
    if not entries:
        return "No new job postings found.\n"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"=== Quarry Digest — {now} ===",
        f"{len(entries)} new posting(s)\n",
    ]

    for i, e in enumerate(entries, 1):
        remote_tag = " [Remote]" if e.get("remote") else ""
        score_tag = f" (score: {e['similarity_score']:.3f})"
        lines.append(f"{i}. {e['title']} at {e['company_name']}{remote_tag}{score_tag}")
        lines.append(f"   {e['location']}")
        lines.append(f"   {e['url']}")
        lines.append("")

    return "\n".join(lines)


def write_digest(entries: list[dict], output_path: str | None = None) -> str:
    """Write formatted digest to a file.

    Args:
        entries: List of posting dicts from build_digest.
        output_path: File path to write to. Defaults to `digest_<timestamp>.txt` in cwd.

    Returns:
        Path to the written file.
    """
    if output_path is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        output_path = f"digest_{timestamp}.txt"

    text = format_digest(entries)
    Path(output_path).write_text(text)
    log.info("Digest written to %s", output_path)

    return output_path


def mark_digest_seen(db: Database, entries: list[dict]) -> None:
    """Mark all digest entries as seen in the database.

    Args:
        db: Database instance.
        entries: List of posting dicts from build_digest.
    """
    posting_ids = [e["id"] for e in entries]
    db.mark_postings_seen(posting_ids)
    log.info("Marked %d postings as seen", len(posting_ids))
```

- [ ] **Step 6: Create `quarry/digest/__main__.py`**

```python
"""Digest CLI entrypoint.

Usage:
    python -m quarry.digest              # Build and write digest file
    python -m quarry.digest --mark-seen  # Also mark included postings as seen
"""

import click

from quarry.config import settings
from quarry.store.db import get_db


@click.command()
@click.option("--mark-seen", is_flag=True, default=False, help="Mark included postings as seen")
@click.option("--limit", default=None, type=int, help="Max postings to include")
@click.option("--output", "-o", default=None, help="Output file path")
def main(mark_seen: bool, limit: int | None, output: str | None):
    """Build and write a digest of new job postings."""
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    from quarry.digest.digest import build_digest, format_digest, write_digest, mark_digest_seen

    db = get_db()
    entries = build_digest(db, limit=limit)

    if not entries:
        click.echo("No new postings found.")
        return

    path = write_digest(entries, output)
    click.echo(f"Digest written to {path} ({len(entries)} postings)")

    if mark_seen:
        mark_digest_seen(db, entries)
        click.echo(f"Marked {len(entries)} postings as seen.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run tests**

Run: `PYTHONPATH=/home/kurtt/job-search pytest tests/test_digest.py -v`
Expected: PASS (after also running the db method addition)

Run all tests: `PYTHONPATH=/home/kurtt/job-search pytest tests/ -v --ignore=tests/test_jobspy_integration.py`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add quarry/digest/ quarry/store/db.py tests/test_digest.py
git commit -m "feat: add digest builder with file output (M7 minimal)"
```

---

## Task 4: Integration test + end-to-end smoke test

**Files:**
- Create: `tests/test_e2e.py`

Verify the whole pipeline works end-to-end with mocked crawlers.

- [ ] **Step 1: Write e2e integration test**

```python
# tests/test_e2e.py
"""End-to-end test: seed → crawl (mocked) → extract → embed → filter → store → digest."""

import pytest
from pathlib import Path
from unittest.mock import patch

import yaml

from quarry.models import Company, RawPosting
from quarry.store.db import Database, init_db


@pytest.fixture
def db(tmp_path):
    return init_db(str(tmp_path / "test.db"))


@pytest.fixture
def seed_file(tmp_path):
    """Create a minimal seed file for testing."""
    data = {
        "companies": [
            {"name": "TestCorp", "ats_type": "greenhouse", "ats_slug": "testcorp"},
        ],
        "search_queries": [
            {"query_text": "People Analytics", "added_reason": "Test"},
        ],
    }
    path = tmp_path / "seed_data.yaml"
    path.write_text(yaml.dump(data))
    return str(path)


class TestEndToEnd:
    def test_seed_crawl_digest(self, db, tmp_path, seed_file):
        """Full pipeline: seed -> crawl (mocked) -> process -> store -> digest."""
        from quarry.agent.tools import seed as do_seed
        from quarry.pipeline.embedder import set_ideal_embedding
        from quarry.agent.scheduler import run_once
        from quarry.digest.digest import build_digest, format_digest, write_digest, mark_digest_seen

        do_seed(db, seed_file)
        set_ideal_embedding(db, "Senior people analytics or HR technology leader")

        mock_posting = RawPosting(
            company_id=1,
            title="Senior People Analytics Manager",
            url="https://example.com/job/e2e1",
            description="Lead the people analytics function at our company. Build dashboards and drive insights.",
            location="Remote, US",
            source_type="greenhouse",
        )

        with patch("quarry.agent.scheduler._crawl_company") as mock_crawl, \
             patch("quarry.agent.scheduler._crawl_search_queries") as mock_search:
            mock_crawl.return_value = [mock_posting]
            mock_search.return_value = []

            summary = run_once(db)

        assert summary["total_found"] >= 1
        assert summary["total_new"] >= 1

        entries = build_digest(db, limit=10)
        assert len(entries) >= 1

        output = tmp_path / "e2e_digest.txt"
        write_digest(entries, str(output))
        assert output.exists()

        content = output.read_text()
        assert "Senior People Analytics Manager" in content

        mark_digest_seen(db, entries)
        new_entries = build_digest(db, limit=10)
        assert len(new_entries) == 0
```

- [ ] **Step 2: Run test**

Run: `PYTHONPATH=/home/kurtt/job-search pytest tests/test_e2e.py -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `PYTHONPATH=/home/kurtt/job-search pytest tests/ -v --ignore=tests/test_jobspy_integration.py`
Expected: All pass

- [ ] **Step 4: Run linter and type checker**

Run: `ruff check quarry/ tests/`
Run: `PYTHONPATH=/home/kurtt/job-search pyright quarry/`

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e.py
git commit -m "test: add end-to-end integration test for seed → crawl → digest pipeline"
```

---

## Self-Review

**1. Spec coverage:**
- Seed loading command (reads from seed_data.yaml, created separately): Task 1 ✓
- Scheduler run_once (crawl → extract → embed → filter → store): Task 2 ✓
- Digest build + file write: Task 3 ✓
- E2E test: Task 4 ✓

**2. Codex review findings addressed:**
- `CrawlRun(status="running")` — **Fixed**: added "running" to the `CrawlRun.status` Literal type in `quarry/models.py`
- `_process_posting` called `get_ideal_embedding()` twice per posting — **Fixed**: ideal_embedding fetched once in `run_once()` and passed as parameter
- `keyword_blocklist` not in config — Acknowledged: `getattr(settings, "keyword_blocklist", [])` works as fallback; config field can be added later
- `get_recent_postings` JOIN with extra `company_name` column — **Fixed**: simplified to `SELECT * FROM job_postings` only, `get_company_name()` provides name separately
- `company_id=0` for unmatched JobSpy results — **Fixed**: extracted to `_resolve_company_id()` helper, returns `None` if no match found (Pydantic allows `None` for `company_id: int | None`)

**3. Placeholder scan:**
- No TBDs, TODOs, or "implement later" in any code blocks. All code is complete.

**4. Type consistency:**
- `RawPosting.company_id` is `int` — `_resolve_company_id` returns `int | None`, used for `company_id: int | None = None` on `JobPosting` ✓
- `build_digest` returns `list[dict]` — `format_digest` and `write_digest` accept `list[dict]` ✓
- `Database.get_recent_postings` returns `list[JobPosting]` — no extra columns ✓
- `Database.mark_postings_seen` accepts `list[int]` as used ✓
- `run_once` return type is `dict` with well-known keys ✓
- `CrawlRun.status` now includes "running" in its Literal ✓