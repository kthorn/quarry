# M2: Crawlers — Design

**Status:** Refined

## Overview

Implement crawlers to fetch job postings from two sources:
1. **JobSpy** — broad discovery across Indeed, Glassdoor, Google Jobs, ZipRecruiter, LinkedIn
2. **ATS endpoints** — company watchlist via Greenhouse, Lever, Ashby APIs

## Architecture

```
scheduler (pull model)
    │
    ├── jobspy_client.py ──→ RawPosting[]
    │
    └── ats_crawlers/
        ├── base.py (ABC)
        ├── greenhouse.py
        ├── lever.py
        ├── ashby.py
        └── careers_page.py (fallback)
```

## Components

### jobspy_client.py

- Thin wrapper around `scrape_jobs()` from `python-jobspy`
- JobSpy returns a pandas DataFrame; convert each row to `RawPosting`
- Requires company resolution step: for each job from JobSpy, look up or create company in DB using company name, then assign `company_id`
- Config-driven: search terms, sites, `hours_old`, `results_wanted`
- Returns `list[RawPosting]`

### base.py

- `BaseCrawler` ABC with abstract method: `async crawl(company: Company) -> list[RawPosting]`
- Async interface for use with asyncio orchestration
- Provides common retry infrastructure using tenacity

### ATS crawlers

| Crawler | Endpoint | Method |
|---------|----------|--------|
| greenhouse | `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true` | GET |
| lever | `https://api.lever.co/v0/postings/{slug}?mode=json` | GET |
| ashby | `https://jobs.ashbyhq.com/api/non-user-graphql` | POST (GraphQL) |
| careers_page | `company.careers_url` | GET + BeautifulSoup (fallback) |

**Careers page fallback security:**
- Validate URL is `https://` only (no http)
- Resolve hostname to IP first, block private/link-local ranges (10.x, 172.16-31.x, 192.168.x, 127.x, ::1)
- Enforce 10s timeout, max 1MB response (stream with hard cap before parse)
- Limit redirects to 5 max, validate redirect target hostname
- Log sanitized URLs (strip query params)

### Fallback routing

| Scenario | Action |
|----------|--------|
| Company has `ats_type: unknown` or `generic` | Use `careers_page.py` fallback |
| ATS crawler fails (timeout, parse error, 5xx) | Log error, skip company for this cycle |
| ATS crawler returns empty list | Accept as valid (no jobs currently open) |

**Ashby GraphQL query:**
```graphql
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
```
(Implementation note: Verify exact query structure during implementation; ARCHITECTURE.md references `jobBoard(organizationHostedJobsPageName: "{slug}")` which may be the correct form.)
Response uses cursor pagination; loop until `jobs` array is empty.

Each crawler:
- Implements `BaseCrawler` (async)
- Parses JSON response
- Extracts all relevant ATS fields into `RawPosting` (title, URL, description, location, remote flag from ATS, posted_at, source_type, source_id)

### source_type and source_id normalization

| Source | source_type | source_id derivation |
|--------|-------------|---------------------|
| JobSpy (Indeed) | `indeed` | JobSpy job ID |
| JobSpy (Glassdoor) | `glassdoor` | JobSpy job ID |
| JobSpy (Google) | `google_jobs` | JobSpy job ID |
| JobSpy (ZipRecruiter) | `zip_recruiter` | JobSpy job ID |
| JobSpy (LinkedIn) | `linkedin` | JobSpy job ID |
| Greenhouse | `greenhouse` | Job ID from API |
| Lever | `lever` | Job ID from API |
| Ashby | `ashby` | Job ID from API |
| Careers page | `careers_page` | URL normalized (lowercase, trailing slash removed) → SHA256, first 16 chars |

### Rate limiting & retries

- Use `tenacity` with exponential backoff
- On 429 (rate limit): retry with exponential backoff, respect `Retry-After` header if present
- On timeout/connection reset: retry with backoff
- On DNS errors: fail immediately (no retry)
- On other HTTP errors (4xx except 429): log error, skip this company (partial success)
- On 5xx server errors: retry with exponential backoff + jitter, max 3 attempts
- Configurable: `max_retries`, `retry_base_delay`
- Bounded concurrency: max 3 concurrent requests per host, orchestrated via `asyncio.gather()` with per-host semaphore

### Error handling

- Per-crawler: catch exception, log to `agent_log`, continue to next company
- Scheduler aggregates partial successes and reports in digest

## Data flow

```
scheduler.run_cycle():
  for each active search_query:
    await jobspy_client.fetch(query) → RawPosting[]
  
  for each active company:
    await ats_crawler.crawl(company) → RawPosting[]
  
  pass all RawPostings to M3 pipeline
```

### M2/M3 responsibility split

- **M2 (crawlers)**: Extract all available ATS fields into `RawPosting`. Store raw location string and any explicit remote flags from ATS. Pass raw data to M3.
- **M3 (extraction pipeline)**: Normalize location string, detect remote via keyword heuristics, clean/normalize description text. M3 is the source of truth for `remote` and `location` after initial M2 extraction.

### Pagination strategy

| Source | Strategy |
|--------|----------|
| Greenhouse | No pagination needed (returns all jobs in single call) |
| Lever | No pagination needed |
| Ashby | Cursor pagination via GraphQL `jobs` field (loop until empty) |
| JobSpy | Built-in pagination via `results_wanted` parameter |
| Careers page | Single page only (fallback, no pagination) |

## Config additions

```yaml
# JobSpy
jobspy_sites:
  - indeed
  - glassdoor
  - google
  - zip_recruiter
  - linkedin
jobspy_results_wanted: 20
jobspy_hours_old: 168
jobspy_location: ""  # optional: "Remote", "US", city name

# Crawler behavior
max_retries: 3
retry_base_delay: 2
max_concurrent_per_host: 3
request_timeout: 10
max_response_bytes: 1048576  # 1MB
max_redirects: 5
```

## Acceptance criteria

1. `jobspy_client.py` returns correctly typed `RawPosting` objects for a test search
2. Each ATS crawler can fetch a known company's postings
3. Rate-limited requests retry with exponential backoff
4. Failed crawlers log error and continue (partial success)
5. Unit tests with fixture JSON for each ATS crawler
6. Integration smoke test for JobSpy
7. Async interface works correctly (await pattern)
8. LinkedIn results included in JobSpy output (best-effort; may be rate-limited)
9. Careers page fallback correctly parses HTML and extracts job listings
10. Cross-source duplicate detection works (best-effort; dedup strategy refined in later phase)

## Dependencies

Already in requirements.txt:
- `python-jobspy>=1.1.0`
- `tenacity>=8.2.0`
- `httpx>=0.27.0`
- `beautifulsoup4>=4.12.0`