# Search-Discovered Companies — Implementation Plan

**Status:** Refined

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix NaN-leaking bug, create search-discovered companies in the shared `companies` table with an inactive `user_watchlist` entry containing rich metadata from JobSpy (domain, ATS type from job URLs), auto-resolve them in the background with concurrency gating, and surface them in the UI for manual activation (which triggers immediate prioritized resolution).

**Architecture:** JobSpy search results create rows in the shared `companies` table (canonical catalog), then add an inactive `user_watchlist` entry (`active=False, added_reason="search"`) linking the company to the user. We extract `company_url_direct` (actual company website) and `job_url_direct` (direct ATS link) from JobSpy rows — the latter lets us detect ATS type (Greenhouse/Lever/Ashby) from URL patterns without HTTP calls. Companies are pre-populated with domain/ATS hints in the shared `companies` table, then background resolution validates via `asyncio.Semaphore(max_concurrent)`. The UI shows a "Discovered" section (watchlist entries where `active=False AND added_reason="search"`) with resolve status; clicking "Activate" immediately resolves the company if needed, then sets `user_watchlist.active=True`.

**Tech Stack:** Python 3.13, Flask, SQLite, pandas, httpx, python-jobspy

**Prerequisite:** This plan assumes the [multi-user schema rebuild](./2026-04-28-schema-rebuild-multiuser.md) has been completed. All per-user state lives in `user_watchlist`, `user_posting_status`, `user_similarity_scores`, etc. The shared `companies` table contains only canonical catalog fields.

> **Review notes** (2026-04-29 plan-reviewer pass): Fixes applied for the following findings:
>
> **Iteration 1:**
>
> - **[FIXED]** `site_name` → `site` — JobSpy returns `site`, not `site_name`
> - **[FIXED]** `job_id` → `id` — JobSpy returns `id`, not `job_id`
> - **[FIXED]** `_extract_domain` uses `removeprefix("www.")` instead of buggy `lstrip("www.")`
> - **[FIXED]** `build_careers_url()` now handles `job-boards.greenhouse.io` pattern
> - **[FIXED]** `resolve_companies_batch` accepts optional external client; sync wrapper closes it
> - **[FIXED]** `_safe_str` noted as already existing; Task 1 reframed as adding regression tests plus domain/ATS extraction
> - **[FIXED]** `asyncio.run()` caveat documented (safe in current sync scheduler; would need refactor if scheduler becomes async)
> - **[FIXED]** `user_id=1` hardcoding documented as matching schema rebuild pattern
> - **[FIXED]** `get_watchlist_companies()` returns `list[dict]`; template guidance added (use `company['name']`)
> - **[FIXED]** `get_companies_by_ids()` noted as used by Task 5 activate route (fetch company for resolution)
> - **[NOTED]** Multi-user schema rebuild must be completed first — this is an explicit prerequisite
> - **[NOTED]** `company_resolver` signature change is a deliberate API break coordinated across the plan
> - **[NOTED]** Seed data loader migration to `user_watchlist` is the schema rebuild plan's responsibility
>
> **Iteration 2 (re-review after fixes):**
>
> - **[FIXED]** `close_client` boolean shadowed the imported `close_client()` function — renamed to `should_close`
> - **[FIXED]** `build_careers_url` comment claimed boards.greenhouse.io is always canonical — corrected to note 301 redirect behavior
> - **[FIXED]** `fetch()` method type hint not updated for new `company_resolver` signature — added explicit Step 5
> - **[FIXED]** `/companies/<id>/activate` hardcoded `added_reason="search"` overwrites provenance — now fetches existing watchlist entry and preserves fields
> - **[FIXED]** `resolve_company_sync` never closed internally-created HTTP client — now accepts optional `client` parameter
> - **[FIXED]** `_crawl_search_queries` missing `user_id` parameter — signature documented in Task 2 context
> - **[FIXED]** Task 6 cleanup SQL hardcoded 29 company names — replaced with dynamic `user_watchlist.added_reason` queries
> - **[FIXED]** `resolve_unresolved_sync` missing optional `client` parameter — added for consistency with batch function
>
> **Iteration 3 (cross-reference against schema rebuild plan):**
>
> - **[FIXED]** All test blocks used `db.init()` (doesn't exist) — replaced with `init_db(":memory:")` directive
> - **[FIXED]** `_default_company_resolver` incompatible signature — updated to accept `(name, hints)`
> - **[FIXED]** `resolve_company_sync` client lifecycle — clarified event loop cleanup in docstring
> - **[FIXED]** `build_careers_url` gap — added `greenhouse_subdomain` field to hints dataclass; detector returns 3-tuple; tests updated
> - **[FIXED]** `get_companies_by_ids` dead code — removed from plan
> - **[FIXED]** `w.active as wl_active` alias breaks template — renamed to `active` (no collision post-rebuild)
> - **[FIXED]** Route conflict with schema rebuild's `companies()` route — reconciliation note added to Task 5
> - **[FIXED]** `get_watchlist_item` not in schema rebuild prerequisite — flagged in Files table
> - **[FIXED]** Test fixture bug (`get_db()` outside app context) — `init_db` directive covers this
> - **[FIXED]** `JobSpyCompanyHints` import scope — module-level import added to Task 2 context
> - **[FIXED]** Files table wrong method name — corrected to `get_watchlist_companies()`
> - **[FIXED]** `docs/sql/` directory may not exist — creation note added to Task 6

---

## Files

| File                                 | Responsibility                                                                                                                                                                                                      |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `quarry/crawlers/jobspy_client.py`   | Fix NaN→"nan" string bug; sanitize all DataFrame fields; extract `company_url_direct` and `job_url_direct`; detect ATS from URL patterns                                                                            |
| `quarry/agent/scheduler.py`          | Create companies in shared `companies` table; insert inactive `user_watchlist` entries (`active=False, added_reason="search"`) with domain/ATS hints from JobSpy; kick off background resolution after search phase |
| `quarry/resolve/pipeline.py`         | Add `resolve_company_sync()` and semaphore-gated `resolve_companies_batch()`; add `detect_ats_from_url()` helper                                                                                                    |
| `quarry/store/db.py`                 | Add `get_watchlist_companies()` filtered by `active`/`added_reason`; add `get_watchlist_item()` single-row lookup                                                                                                   |
| `quarry/ui/routes.py`                | Add `/companies/<id>/activate` route that resolves then activates; pass discovered list to template (builds on schema rebuild's dict-based companies route)                                                         |
| `quarry/ui/templates/companies.html` | Add "Discovered" section with resolve status, domain, careers URL, Activate button                                                                                                                                  |
| `tests/test_jobspy_client.py`        | Test NaN handling, domain extraction, ATS URL detection                                                                                                                                                             |
| `tests/test_scheduler.py`            | Test search phase creates companies in shared table + inactive watchlist entries                                                                                                                                    |
| `tests/test_ui.py`                   | Test discovered companies appear in template context; test activate triggers resolution                                                                                                                             |
| `quarry/store/schema.py`             | (No changes needed; multi-user schema already has `user_watchlist` and `companies`)                                                                                                                                 |

---

## Task 1: Fix NaN Bug + Extract JobSpy Metadata in jobspy_client.py

**Files:**

- Modify: `quarry/crawlers/jobspy_client.py`
- Test: `tests/test_jobspy_client.py`

**Context:** `_safe_str` already exists in `jobspy_client.py:109` and handles NaN/None/empty/whitespace correctly. This task adds regression tests for it and implements the new `_extract_domain()` and `_detect_ats_from_url()` helpers. Also fixes two column-name bugs: JobSpy returns `site` (not `site_name`) and `id` (not `job_id`).

- [ ] **Step 1: Write tests for new helpers (and regression tests for `_safe_str`)**

> **Note:** `tests/test_jobspy_client.py` is a new test file. All test code in this plan uses `init_db(":memory:")` (from the schema rebuild plan) instead of the old `db.init()` pattern. Also update the `fetch()` method signature in `jobspy_client.py` from `Callable[[str], Company]` to `Callable[[str, JobSpyCompanyHints], Company]` to match the new `_convert_dataframe` callback signature.

```python
import math

import pytest

from quarry.crawlers.jobspy_client import JobSpyClient


class TestSafeStr:
    def test_nan_returns_default(self):
        assert JobSpyClient._safe_str(float("nan"), "Unknown") == "Unknown"

    def test_none_returns_default(self):
        assert JobSpyClient._safe_str(None, "Unknown") == "Unknown"

    def test_empty_string_returns_default(self):
        assert JobSpyClient._safe_str("", "Unknown") == "Unknown"

    def test_whitespace_only_returns_default(self):
        assert JobSpyClient._safe_str("   ", "Unknown") == "Unknown"

    def test_valid_string_returns_stripped(self):
        assert JobSpyClient._safe_str("  Acme  ", "Unknown") == "Acme"

    def test_pandas_na_returns_default(self):
        import pandas as pd
        assert JobSpyClient._safe_str(pd.NA, "Unknown") == "Unknown"


class TestExtractDomain:
    def test_extracts_clean_domain(self):
        assert JobSpyClient._extract_domain("https://www.amperecomputing.com/careers") == "amperecomputing.com"

    def test_strips_www(self):
        assert JobSpyClient._extract_domain("http://www.example.com") == "example.com"

    def test_removeprefix_not_lstrip(self):
        # Ensure we use removeprefix (not lstrip, which strips any combo of w/. chars)
        assert JobSpyClient._extract_domain("https://ww2.example.com") == "ww2.example.com"

    def test_none_returns_none(self):
        assert JobSpyClient._extract_domain(None) is None

    def test_empty_returns_none(self):
        assert JobSpyClient._extract_domain("") is None


class TestDetectAtsFromUrl:
    def test_greenhouse_boards(self):
        assert JobSpyClient._detect_ats_from_url(
            "https://boards.greenhouse.io/openai/jobs/123"
        ) == ("greenhouse", "openai", "boards")

    def test_greenhouse_api(self):
        assert JobSpyClient._detect_ats_from_url(
            "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs"
        ) == ("greenhouse", "anthropic", "boards")

    def test_greenhouse_job_boards(self):
        assert JobSpyClient._detect_ats_from_url(
            "https://job-boards.greenhouse.io/deepmind/123"
        ) == ("greenhouse", "deepmind", "job-boards")

    def test_lever(self):
        assert JobSpyClient._detect_ats_from_url(
            "https://jobs.lever.co/huggingface/abc-123"
        ) == ("lever", "huggingface", None)

    def test_ashby(self):
        assert JobSpyClient._detect_ats_from_url(
            "https://jobs.ashbyhq.com/cognition/123"
        ) == ("ashby", "cognition", None)

    def test_ashby_careers(self):
        assert JobSpyClient._detect_ats_from_url(
            "https://careers.ashbyhq.com/openai/123"
        ) == ("ashby", "openai", None)

    def test_unknown_url(self):
        assert JobSpyClient._detect_ats_from_url("https://example.com/jobs") == (None, None, None)

    def test_none_url(self):
        assert JobSpyClient._detect_ats_from_url(None) == (None, None, None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_jobspy_client.py -v`
Expected: `_safe_str` tests PASS (already implemented), `_extract_domain`/`_detect_ats_from_url` tests FAIL

- [ ] **Step 3: Implement new helpers (`_extract_domain`, `_detect_ats_from_url`) and update `_convert_dataframe`**

Add to `JobSpyClient` class in `quarry/crawlers/jobspy_client.py`:

```python
    # NOTE: _safe_str already exists in jobspy_client.py:109 — do not redefine.
    # The tests in test_jobspy_client.py serve as regression coverage.

    @staticmethod
    def _extract_domain(url: str | None) -> str | None:
        """Extract clean domain from a URL, or None if invalid."""
        if not url:
            return None
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.hostname:
            return parsed.hostname.lower().removeprefix("www.")
        return None

    @staticmethod
    def _detect_ats_from_url(url: str | None) -> tuple[str | None, str | None, str | None]:
        """Detect ATS type, slug, and greenhouse subdomain from a direct job board URL.

        Returns (ats_type, ats_slug, greenhouse_subdomain) or (None, None, None).
        """
        if not url:
            return None, None
        import re
        patterns = [
            (r"boards\.greenhouse\.io/([^/]+)", "greenhouse", "boards"),
            (r"boards-api\.greenhouse\.io/v1/boards/([^/]+)", "greenhouse", "boards"),
            (r"job-boards\.greenhouse\.io/([^/]+)", "greenhouse", "job-boards"),
            (r"jobs\.lever\.co/([^/]+)", "lever", None),
            (r"jobs\.ashbyhq\.com/([^/]+)", "ashby", None),
            (r"careers\.ashbyhq\.com/([^/]+)", "ashby", None),
        ]
        for pattern, ats_type, subdomain in patterns:
            match = re.search(pattern, url)
            if match:
                return ats_type, match.group(1), subdomain
        return None, None, None
```

Update `_convert_dataframe` — the company resolver callback now returns a tuple of `(Company, domain_hint, ats_type_hint, ats_slug_hint)` so the caller can use the hints for watchlist insertion:

```python
from dataclasses import dataclass

@dataclass
class JobSpyCompanyHints:
    """Per-row company hints extracted from JobSpy metadata."""
    domain_hint: str | None
    ats_type_hint: str | None
    ats_slug_hint: str | None
    greenhouse_subdomain: str | None = None  # "boards" or "job-boards" for greenhouse URLs

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
```

```python
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

            source_type = SITE_NAME_TO_SOURCE_TYPE.get(
                site.lower(), site.lower()
            )

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

            posting = RawPosting(
                company_id=company_id,
                title=self._safe_str(row.get("title"), "Unknown"),
                url=self._safe_str(row.get("url"), ""),
                description=self._safe_str(row.get("description"))
                if pd.notna(row.get("description"))
                else None,
                location=self._safe_str(row.get("location"))
                if pd.notna(row.get("location"))
                else None,
                posted_at=row.get("date_posted"),
                # NOTE: JobSpy column is 'id', not 'job_id' — verified empirically
                source_id=self._safe_str(row.get("id"), ""),
                source_type=str(source_type),
            )
            postings.append(posting)

        return postings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_jobspy_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quarry/crawlers/jobspy_client.py tests/test_jobspy_client.py
git commit -m "fix: add domain/ATS extraction, fix JobSpy column names, regression tests

- Add _extract_domain() to get clean domain from company_url_direct
- Add _detect_ats_from_url() to identify Greenhouse/Lever/Ashby from job_url_direct
- Add JobSpyCompanyHints dataclass to bundle domain/ATS hints for callers
- Fix column names: site_name→site, job_id→id (verified against JobSpy output)
- Regression tests for _safe_str (already implemented, NaN handling works)
- Add removeprefix test to guard against lstrip bug"

```

---

## Task 2: Create Search-Discovered Companies (Shared) + Watchlist Entries (Per-User)

````

---

## Task 2: Create Search-Discovered Companies (Shared) + Watchlist Entries (Per-User)

**Files:**

- Modify: `quarry/agent/scheduler.py` (`_crawl_search_queries` method)
- Test: `tests/test_scheduler.py`

**Context:** With the multi-user schema, companies live in the shared `companies` table (canonical catalog), and per-user status lives in `user_watchlist`. A search-discovered company is:

1. A row in `companies` with domain/ATS hints pre-populated
2. A row in `user_watchlist` with `active=False, added_reason="search"`

Also update `_crawl_search_queries` signature from `def _crawl_search_queries(db: Database)` to `def _crawl_search_queries(db: Database, user_id: int = 1)` so the `company_resolver` closure can pass `user_id` through. Add `from quarry.crawlers.jobspy_client import JobSpyCompanyHints` at the top of `scheduler.py` (module-level import, not inside the function body).

If the company already exists in `companies`, we still add the watchlist entry if one doesn't already exist. If the company already exists in the user's watchlist (e.g., from seed data), we leave it alone.

- [ ] **Step 1: Extract `resolve_or_create_search_company` with hint support**

In `quarry/agent/scheduler.py`, add module-level function:

```python
def resolve_or_create_search_company(
    db: Database,
    name: str,
    hints: JobSpyCompanyHints,
    user_id: int = 1,
) -> Company:
    """Look up or create a company in the shared table, and ensure a watchlist entry.

    If the company is new, populate domain/ATS hints from JobSpy metadata.
    Always adds a user_watchlist entry (active=False, added_reason='search')
    unless one already exists for this user.
    """
    from quarry.models import Company, UserWatchlistItem
    from quarry.crawlers.jobspy_client import JobSpyCompanyHints

    company = db.get_company_by_name(name)
    if company is None:
        # Determine ATS type and resolve status from hints
        ats_type = hints.ats_type_hint or "unknown"
        ats_slug = hints.ats_slug_hint
        domain = hints.domain_hint
        careers_url = hints.build_careers_url()

        # If we detected an ATS from the job URL, mark as resolved
        resolve_status = "resolved" if hints.ats_type_hint else "unresolved"

        company = Company(
            name=name,
            domain=domain,
            careers_url=careers_url,
            ats_type=ats_type,
            ats_slug=ats_slug,
            resolve_status=resolve_status,
        )
        company.id = db.insert_company(company)

    # Ensure a watchlist entry exists (don't overwrite if already present)
    existing_wl = db.get_watchlist_item(user_id, company.id)
    if existing_wl is None:
        db.upsert_watchlist_item(
            UserWatchlistItem(
                user_id=user_id,
                company_id=company.id,
                active=False,
                added_reason="search",
            )
        )

    return company
````

Replace the inline closure in `_crawl_search_queries`:

```python
    def company_resolver(name: str, hints: JobSpyCompanyHints) -> Company:
        lower = name.lower()
        if lower in seen_companies:
            return seen_companies[lower]
        company = resolve_or_create_search_company(
            db, name, hints, user_id=user_id,
        )
        seen_companies[lower] = company
        return company
```

- [ ] **Step 2: Add `get_watchlist_item` to Database class**

In `quarry/store/db.py`:

```python
    def get_watchlist_item(self, user_id: int, company_id: int) -> models.UserWatchlistItem | None:
        rows = self.execute(
            "SELECT * FROM user_watchlist WHERE user_id = ? AND company_id = ?",
            (user_id, company_id),
        )
        return models.UserWatchlistItem(**dict(rows[0])) if rows else None
```

- [ ] **Step 3: Write tests**

```python
def test_resolve_or_create_search_company_creates_company_in_shared_table():
    from quarry.agent.scheduler import resolve_or_create_search_company
    from quarry.models import Company
    from quarry.crawlers.jobspy_client import JobSpyCompanyHints

    db = Database(":memory:")
    db.init()
    db._seed_default_user()

    hints = JobSpyCompanyHints(domain_hint=None, ats_type_hint=None, ats_slug_hint=None)
    result = resolve_or_create_search_company(db, "NovelCo", hints, user_id=1)

    assert result.name == "NovelCo"
    assert result.resolve_status == "unresolved"

    # Verify in shared table
    fetched = db.get_company_by_name("NovelCo")
    assert fetched is not None

    # Verify watchlist entry
    wl = db.get_watchlist_item(1, result.id)
    assert wl is not None
    assert wl.active is False
    assert wl.added_reason == "search"


def test_resolve_or_create_search_company_uses_hints():
    from quarry.agent.scheduler import resolve_or_create_search_company
    from quarry.crawlers.jobspy_client import JobSpyCompanyHints

    db = Database(":memory:")
    db.init()
    db._seed_default_user()

    hints = JobSpyCompanyHints(
        domain_hint="acme.com",
        ats_type_hint="greenhouse",
        ats_slug_hint="acme",
    )
    result = resolve_or_create_search_company(db, "Acme", hints, user_id=1)

    assert result.domain == "acme.com"
    assert result.ats_type == "greenhouse"
    assert result.ats_slug == "acme"
    assert result.resolve_status == "resolved"
    assert result.careers_url == "https://boards.greenhouse.io/acme"


def test_resolve_or_create_search_company_returns_existing_does_not_overwrite_watchlist():
    from quarry.agent.scheduler import resolve_or_create_search_company
    from quarry.models import Company, UserWatchlistItem
    from quarry.crawlers.jobspy_client import JobSpyCompanyHints

    db = Database(":memory:")
    db.init()
    db._seed_default_user()

    company = Company(name="ExistingCo")
    company.id = db.insert_company(company)

    # Seed company already in watchlist (active)
    db.upsert_watchlist_item(
        UserWatchlistItem(user_id=1, company_id=company.id, active=True, added_reason="seed")
    )

    hints = JobSpyCompanyHints(domain_hint=None, ats_type_hint=None, ats_slug_hint=None)
    result = resolve_or_create_search_company(db, "ExistingCo", hints, user_id=1)

    assert result.id == company.id

    # Watchlist should NOT be overwritten to inactive/search
    wl = db.get_watchlist_item(1, company.id)
    assert wl.active is True
    assert wl.added_reason == "seed"
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quarry/agent/scheduler.py quarry/store/db.py tests/test_scheduler.py
git commit -m "feat: create search-discovered companies in shared table + inactive watchlist entries

- Extract resolve_or_create_search_company() from inline closure
- Accepts JobSpyCompanyHints with domain_hint, ats_type_hint, ats_slug_hint
- Creates company in shared companies table with pre-populated hints
- Adds inactive user_watchlist entry (active=False, added_reason='search')
- Does NOT overwrite existing watchlist entries (preserves seed data)
- Marks as resolved when ATS detected from job_url_direct pattern
- Added get_watchlist_item() DB helper"
```

---

## Task 3: Add Semaphore-Gated Background Resolution

**Files:**

- Modify: `quarry/resolve/pipeline.py`
- Modify: `quarry/agent/scheduler.py`
- Test: `tests/test_resolve_pipeline.py` (new or existing)

**Context:** After search crawl, we want to resolve all unresolved companies without overwhelming external services. Use `asyncio.Semaphore(max_concurrent)` where `max_concurrent` comes from `settings.max_concurrent_per_host` (default 3). Since `resolve_status` lives on the shared `companies` table, resolution works the same regardless of per-user state.

- [ ] **Step 1: Add `resolve_companies_batch` with semaphore**

In `quarry/resolve/pipeline.py`:

```python
async def resolve_companies_batch(
    db: Database,
    companies: list[Company],
    max_concurrent: int = 3,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Resolve a batch of companies with concurrency gating.

    Accepts an optional external client. If none is provided, a new client
    is created and closed when the batch completes.
    """
    should_close = client is None
    if client is None:
        client = get_client()

    try:
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _resolve_one(company: Company) -> None:
            async with semaphore:
                try:
                    await resolve_company(company, db=db, client=client)
                except Exception as e:
                    log.error("Error resolving %s: %s", company.name, e)

        await asyncio.gather(*[_resolve_one(c) for c in companies])
    finally:
        if should_close:
            await close_client()
```

- [ ] **Step 2: Add sync wrappers**

```python
def resolve_unresolved_sync(
    db: Database,
    max_concurrent: int = 3,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Synchronous entrypoint to resolve all unresolved companies.

    Accepts an optional external client (passed through to resolve_companies_batch).

    Uses asyncio.run() which creates a fresh event loop. This is safe as long
    as the caller is not already inside a running event loop (which the current
    synchronous scheduler is not). If the scheduler ever becomes async, refactor
    to call resolve_companies_batch directly instead of using this wrapper.
    """
    import asyncio

    companies = db.get_companies_by_resolve_status("unresolved")
    if not companies:
        return
    log.info("Resolving %d unresolved companies (max_concurrent=%d)", len(companies), max_concurrent)
    asyncio.run(resolve_companies_batch(db, companies, max_concurrent=max_concurrent, client=client))


def resolve_company_sync(
    company: Company,
    db: Database | None = None,
    client: httpx.AsyncClient | None = None,
) -> Company:
    """Synchronous entrypoint to resolve a single company.

    Uses asyncio.run() which creates a fresh event loop. Any internally-created
    HTTP client is bound to that loop's lifecycle and cleaned up on exit.
    Repeated calls create/destroy event loops — acceptable for the current
    single-user CLI/UI tool. If called frequently from a long-running server,
    refactor to use a shared client and event loop.
    """
    import asyncio
    return asyncio.run(resolve_company(company, db=db, client=client))
```

- [ ] **Step 3: Kick off background resolution after search in scheduler**

In `quarry/agent/scheduler.py`, after `_crawl_search_queries` returns:

```python
    search_postings = _crawl_search_queries(db)
    total_found += len(search_postings)
    log.info("Phase: processing %d search query results", len(search_postings))

    # Resolve newly discovered companies in the background
    from quarry.resolve.pipeline import resolve_unresolved_sync
    resolve_unresolved_sync(db, max_concurrent=settings.max_concurrent_per_host)
```

- [ ] **Step 4: Add tests for batch resolution**

```python
import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from quarry.models import Company
from quarry.resolve.pipeline import resolve_companies_batch


@pytest.mark.asyncio
async def test_resolve_companies_batch_respects_semaphore():
    """Only max_concurrent resolutions run at once."""
    db = Mock()
    companies = [Company(name=f"Co{i}", id=i) for i in range(5)]

    active_count = 0
    max_observed = 0

    async def fake_resolve(company, db=None, client=None):
        nonlocal active_count, max_observed
        active_count += 1
        max_observed = max(max_observed, active_count)
        await asyncio.sleep(0.01)
        active_count -= 1

    with patch("quarry.resolve.pipeline.resolve_company", side_effect=fake_resolve):
        await resolve_companies_batch(db, companies, max_concurrent=2)

    assert max_observed <= 2
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_resolve_pipeline.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add quarry/resolve/pipeline.py quarry/agent/scheduler.py tests/test_resolve_pipeline.py
git commit -m "feat: semaphore-gated background resolution for discovered companies

- Add resolve_companies_batch() with asyncio.Semaphore(max_concurrent)
- Add resolve_unresolved_sync() and resolve_company_sync() entrypoints
- Scheduler calls resolve_unresolved_sync after JobSpy search phase
- Configurable via settings.max_concurrent_per_host (default 3)"
```

---

## Task 4: DB Helpers — Watchlist Filtering + Bulk Fetch

**Files:**

- Modify: `quarry/store/db.py`
- Test: `tests/test_db.py`

**Context:** The UI needs to show "discovered" companies — those in the user's watchlist with `active=False` and `added_reason="search"`. We need a query that joins `user_watchlist` → `companies` and filters by these criteria, plus a bulk fetch for company objects.

- [ ] **Step 1: Add `get_watchlist_companies()` with filter support**

```python
    def get_watchlist_companies(
        self,
        user_id: int = 1,
        active: bool | None = None,
        added_reason: str | None = None,
    ) -> list[dict]:
        """Get companies from user's watchlist, joined with company details.

        Returns list of dicts with all company columns + watchlist columns.
        """
        sql = """
            SELECT c.*, w.active, w.crawl_priority, w.notes, w.added_reason
            FROM user_watchlist w
            JOIN companies c ON c.id = w.company_id
            WHERE w.user_id = ?
        """
        params: list = [user_id]
        if active is not None:
            sql += " AND w.active = ?"
            params.append(1 if active else 0)
        if added_reason is not None:
            sql += " AND w.added_reason = ?"
            params.append(added_reason)
        sql += " ORDER BY c.name"
        rows = self.execute(sql, params)
        return [dict(row) for row in rows]
```

- [ ] **Step 2: Add tests**

> **Note:** After the schema rebuild, the `companies` table drops its `active` column, so `w.active` has no name collision. Templates use `company.active` (via Jinja2 dict access) to read the watchlist active flag.

```python
def test_get_watchlist_companies_filters_discovered():
    db = init_db(":memory:")

    # Create two companies, one seed (active), one search (inactive)
    db.insert_company(Company(name="SeedCo"))
    db.insert_company(Company(name="SearchCo"))
    seed = db.get_company_by_name("SeedCo")
    search = db.get_company_by_name("SearchCo")

    db.upsert_watchlist_item(
        UserWatchlistItem(user_id=1, company_id=seed.id, active=True, added_reason="seed")
    )
    db.upsert_watchlist_item(
        UserWatchlistItem(user_id=1, company_id=search.id, active=False, added_reason="search")
    )

    # Active only
    active = db.get_watchlist_companies(user_id=1, active=True)
    assert len(active) == 1
    assert active[0]["name"] == "SeedCo"

    # Inactive search-discovered only
    discovered = db.get_watchlist_companies(user_id=1, active=False, added_reason="search")
    assert len(discovered) == 1
    assert discovered[0]["name"] == "SearchCo"
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_db.py -v -k "watchlist_companies"`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add quarry/store/db.py tests/test_db.py
git commit -m "feat: add get_watchlist_companies() DB helper with active/added_reason filters

- get_watchlist_companies() joins user_watchlist → companies
- w.active aliased as 'active' (no collision after schema rebuild drops companies.active)
- Returns list[dict] with active, crawl_priority, notes, added_reason"
```

---

## Task 5: UI — Show Discovered Companies + Activate with Prioritized Resolution

**Files:**

- Modify: `quarry/ui/routes.py`
- Modify: `quarry/ui/templates/companies.html`
- Test: `tests/test_ui.py`

- [ ] **Step 1: Add `/companies/<id>/activate` route**

```python
@bp.route("/companies/<int:company_id>/activate", methods=["POST"])
def activate_company(company_id):
    """Activate a discovered company, resolving it first if needed."""
    db = get_db()
    company = db.get_company(company_id)
    if company is None:
        return "Company not found", 404

    if company.resolve_status != "resolved":
        from quarry.resolve.pipeline import resolve_company_sync
        company = resolve_company_sync(company, db=db)

    # Mark watchlist entry as active, preserving existing provenance
    existing_wl = db.get_watchlist_item(user_id=1, company_id=company.id)
    db.upsert_watchlist_item(
        models.UserWatchlistItem(
            user_id=1,  # TODO: replace with auth
            company_id=company.id,
            active=True,
            added_reason=existing_wl.added_reason if existing_wl else "search",
            crawl_priority=existing_wl.crawl_priority if existing_wl else 5,
            notes=existing_wl.notes if existing_wl else None,
        )
    )
    return redirect(url_for("ui.companies"))
```

- [ ] **Step 2: Update companies route**

> **Route design note:** This plan builds on the schema rebuild plan's `/companies` route. The rebuild plan uses `db.get_watchlist()` to return `Company` objects for active/inactive lists. This plan adds a third `discovered` list using `get_watchlist_companies()` which returns dicts. The template must handle both types or the routes should be unified. For consistency, this plan's approach (all three lists as dicts from `get_watchlist_companies`) is preferred — update the schema rebuild plan's route accordingly when implementing.

```python
@bp.route("/companies")
def companies():
    db = get_db()

    # Active companies (watchlist where active=True)
    active = db.get_watchlist_companies(user_id=1, active=True)

    # Inactive non-search companies (e.g., manually deactivated)
    inactive = [
        c for c in db.get_watchlist_companies(user_id=1, active=False)
        if c.get("added_reason") != "search"
    ]

    # Discovered via search (watchlist where active=False, added_reason="search")
    discovered = db.get_watchlist_companies(user_id=1, active=False, added_reason="search")

    return render_template(
        "companies.html",
        active=active,
        inactive=inactive,
        discovered=discovered,
    )
```

- [ ] **Step 3: Update template**

> **Note:** `get_watchlist_companies()` returns `list[dict]`, so templates use `company['name']` (dict access) instead of `company.name` (attribute access). If this is awkward, the route can convert dicts to lightweight objects before passing to the template.

Add "Discovered via Search" section:

```html
<h2>Discovered via Search ({{ discovered|length }})</h2>
{% if discovered %}
<table>
  <thead>
    <tr>
      <th>Name</th>
      <th>Status</th>
      <th>Domain</th>
      <th>Careers URL</th>
      <th>Action</th>
    </tr>
  </thead>
  <tbody>
    {% for company in discovered %}
    <tr>
      <td>{{ company.name }}</td>
      <td>{{ company.resolve_status }}</td>
      <td>{{ company.domain or "\u2014" }}</td>
      <td>
        {% if company.careers_url %}<a href="{{ company.careers_url }}"
          >{{ company.careers_url }}</a
        >{% else %}\u2014{% endif %}
      </td>
      <td>
        <form
          method="POST"
          action="{{ url_for('ui.activate_company', company_id=company.id) }}"
          class="inline"
        >
          <button type="submit" class="small btn-applied">Activate</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% else %}
<p>No companies discovered via search yet.</p>
{% endif %}
```

- [ ] **Step 4: Add UI test**

```python
def test_companies_page_shows_discovered():
    from quarry.models import Company, UserWatchlistItem
    db = get_db()
    db.init()
    db._seed_default_user()

    company = Company(name="SearchCo")
    company.id = db.insert_company(company)
    db.upsert_watchlist_item(
        UserWatchlistItem(user_id=1, company_id=company.id, active=False, added_reason="search")
    )

    # Also create a seed company
    seed = Company(name="SeedCo")
    seed.id = db.insert_company(seed)
    db.upsert_watchlist_item(
        UserWatchlistItem(user_id=1, company_id=seed.id, active=True, added_reason="seed")
    )

    with app.test_client() as client:
        resp = client.get("/companies")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Discovered via Search" in html
        assert "SearchCo" in html
        assert "SeedCo" in html
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_ui.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add quarry/ui/routes.py quarry/ui/templates/companies.html tests/test_ui.py
git commit -m "feat: show search-discovered companies in UI with prioritized activation

- Add 'Discovered via Search' section to /companies page
- Uses get_watchlist_companies(user_id=1, active=False, added_reason='search')
- Shows resolve_status, domain, careers URL from shared companies table
- Activate button triggers immediate resolution if needed, then sets watchlist.active=True
- New /companies/<id>/activate route"
```

---

## Task 6: Data Cleanup

**Files:**

- Modify: `quarry.db`

**Context:** After the schema rebuild, the database has the multi-user schema. We need to clean up any "nan" or empty-name companies and ensure search-discovered companies have correct `user_watchlist` entries. Since the schema rebuild drops the old DB and seeds fresh, there may not be much cleanup needed. But if any data has accumulated after the rebuild, run the following SQL script (do NOT commit the binary `quarry.db` — committing SQL scripts is preferred for repo hygiene). This script uses `user_watchlist.added_reason = 'seed'` to identify seed companies dynamically rather than hardcoding company names.

Run this SQL:

```sql
-- Delete the literal 'nan' company and any empty-name companies
DELETE FROM companies WHERE name = 'nan' OR name = '' OR name = 'Unknown';

-- Ensure all non-seed companies have inactive search-discovered watchlist entries
-- Uses watchlist metadata instead of hardcoding company names
INSERT OR IGNORE INTO user_watchlist (user_id, company_id, active, added_reason)
SELECT 1, c.id, 0, 'search'
FROM companies c
WHERE NOT EXISTS (
    SELECT 1 FROM user_watchlist w WHERE w.company_id = c.id
);

-- Ensure seed companies have active watchlist entries (already handled by seed())
-- Seed companies are identified by existing watchlist entries with added_reason='seed'
INSERT OR IGNORE INTO user_watchlist (user_id, company_id, active, added_reason)
SELECT 1, c.id, 1, 'seed'
FROM user_watchlist w
JOIN companies c ON c.id = w.company_id
WHERE w.added_reason = 'seed'
  AND w.active = 0;
```

Verify:

```sql
SELECT w.active, w.added_reason, COUNT(*)
FROM user_watchlist w
JOIN companies c ON c.id = w.company_id
WHERE w.user_id = 1
GROUP BY w.active, w.added_reason;
```

Commit the cleanup SQL as a migration script rather than committing the binary DB (create `docs/sql/` directory if it doesn't exist):

```bash
git add docs/sql/cleanup_search_discovered.sql
git commit -m "data: add cleanup SQL for search-discovered companies

- Delete 'nan' company and empty-name companies
- Ensure non-seed companies have inactive watchlist entries (added_reason='search')
- Ensure seed companies have active watchlist entries (added_reason='seed')
- Uses dynamic watchlist metadata queries instead of hardcoded company names"
```

---

## Task 7: Full Verification

- [ ] **Run all tests**

```bash
source /home/kurtt/miniforge3/bin/activate quarry
python -m pytest tests/ -q
```

Expected: all tests passing (count will depend on schema rebuild baseline)

- [ ] **Run linter and type checker**

```bash
ruff check .
pyright quarry/
```

Expected: clean

- [ ] **End-to-end smoke test**

```bash
python -m quarry.agent run-once
```

Verify the scheduler completes without errors and search-discovered companies appear in `user_watchlist`.

- [ ] **Update STATUS.md**

```markdown
- **Search-discovered companies**: JobSpy-discovered companies created in shared `companies` table with domain/ATS hints from `company_url_direct`/`job_url_direct` URL patterns; linked via inactive `user_watchlist` entries (`active=False, added_reason='search'`); auto-resolved in background with `asyncio.Semaphore`; surfaced in UI "Discovered" section with Activate button
- **NaN bug fix**: JobSpy DataFrame values sanitized via `_safe_str()` before creating companies/postings
```

- [ ] **Final commit**

```bash
git add docs/STATUS.md
git commit -m "docs: update STATUS.md for search-discovered companies"
```

---

## Spec Coverage

| Requirement                                                             | Task   |
| ----------------------------------------------------------------------- | ------ |
| NaN doesn't leak as company name                                        | Task 1 |
| Extract domain from `company_url_direct`                                | Task 1 |
| Detect ATS from `job_url_direct` patterns                               | Task 1 |
| Search-discovered companies in shared `companies` table                 | Task 2 |
| Inactive `user_watchlist` entry with `added_reason="search"`            | Task 2 |
| Not auto-crawled (watchlist `active=False`)                             | Task 2 |
| Existing watchlist entries (seed) not overwritten                       | Task 2 |
| Background resolution with semaphore (`resolve_status` on shared table) | Task 3 |
| UI shows discovered companies separately                                | Task 5 |
| Activate triggers immediate resolution then sets `active=True`          | Task 5 |
| Existing data cleaned up (watchlist entries)                            | Task 6 |
