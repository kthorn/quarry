# Company Resolver Design

## Problem

When JobSpy search results create companies, they only get a `name` — no `domain`, `careers_url`, `ats_type`, or `ats_slug`. The crawler dispatcher routes `ats_type="unknown"` to `CareersPageCrawler`, which immediately returns `[]` because `careers_url` is `None`. Currently 116 out of 145 companies are un-crawlable dead ends.

## Approach

**Resolver Pipeline** — a new `quarry/resolve/` package with independent, composable resolvers chained in sequence:

1. **DomainResolver** — company name → domain (guess-and-probe)
2. **CareersUrlResolver** — domain → careers_url (URL probing)
3. **AtsDetector** — careers_url → (ats_type, ats_slug)

Each resolver is idempotent (skips companies that already have the field) and persists progress after each step.

The `detect_ats()` function in `ats_detector.py` is shared with the CLI — `add-company` calls it inline for URL-pattern detection, while the full pipeline invokes both phases (URL patterns + HTML signatures).

## Module Structure

```
quarry/
  http.py               # Shared httpx.AsyncClient singleton (new)
  resolve/
    __init__.py          # Public API: resolve_company(), resolve_unresolved()
    domain_resolver.py   # Company name → domain
    careers_resolver.py  # Domain → careers_url
    ats_detector.py      # careers_url → (ats_type, ats_slug) — also imported by CLI for inline URL-pattern detection
    pipeline.py          # Orchestrates the 3 resolvers in sequence
```

## Shared HTTP Client (`quarry/http.py`)

A process-level `httpx.AsyncClient` singleton used by all crawlers and resolvers:

- Lazy-initialized with sensible defaults (timeouts, follow redirects, connection pooling)
- Single place to configure user-agent, rate-limiting, retries
- `get_client()` returns the singleton; `close_client()` for clean shutdown
- Refactor existing `AsyncClient` instantiations in `greenhouse.py`, `lever.py`, `ashby.py`, and `careers_page.py` to use it

**Async/sync boundary:** The resolver pipeline (`domain_resolver`, `careers_resolver`) and HTML-signature detection in `ats_detector` are async (they make HTTP requests). The CLI and `run_once()` entrypoints are synchronous. `pipeline.py` wraps the async pipeline with `asyncio.run()` for synchronous callers. `resolve_company()` is the async entry point; `resolve_unresolved()` calls it via `asyncio.run()` in a loop.

## Resolver Pipeline Flow

```
Company(name="Takeda Pharmaceuticals", domain=None, careers_url=None, ats_type="unknown")
  │
  ▼ domain_resolver
Company(name="Takeda Pharmaceuticals", domain="takeda.com", ...)
  │
  ▼ careers_resolver
Company(name="Takeda Pharmaceuticals", domain="takeda.com", careers_url="https://takeda.com/careers", ...)
  │
  ▼ ats_detector
Company(name="Takeda Pharmaceuticals", domain="takeda.com", careers_url="https://takeda.com/careers", ats_type="greenhouse", ats_slug="takeda")
```

Each step persists to DB immediately via `db.update_company()`. If the pipeline crashes mid-way, partial progress is preserved. Note: `resolve_status` is only set to `'resolved'` after all applicable resolvers complete successfully — not after each individual step. This prevents a company from being stuck in `'resolved'` with `ats_type="unknown"`, which would cause `resolve_unresolved()` to skip it on future runs.

## Domain Resolver

Derives a company's website domain from its name.

**Strategy (short-circuit on first success):**

1. **Skip if `domain` already set** — idempotent
2. **Normalize the name** — strip suffixes: `Inc.`, `LLC`, `Co.`, `Corp.`, `Group`, `Holdings`, `.com` suffix, etc.
3. **Guess-and-probe `{normalized}.com`** — HTTPS HEAD request, 10s timeout, follow redirects
4. **Try transformations** — hyphens for spaces (`Takeda Pharmaceuticals` → `takeda-pharmaceuticals.com`), drop words from the end (`Takeda`)
5. **Mark `resolve_status='failed'`** if nothing resolves, increment `resolve_attempts`

Intentionally simple for V1 — resolves obvious `.com` companies. Non-obvious domains (government labs, companies with `.ai`/`.io` TLDs, etc.) will fail and be marked for future web search resolution.

## Careers URL Resolver

Probes common careers URL patterns on a resolved domain.

**Strategy:**

1. **Skip if `careers_url` already set** — idempotent
2. **Skip if no `domain`** — can't resolve, stays `unresolved`
3. **Probe URL patterns in priority order:**
   - `https://{domain}/careers`
   - `https://{domain}/jobs`
   - `https://{domain}/careers/search`
   - `https://{domain}/about/careers`
   - `https://{domain}/en/careers`
   - `https://www.{domain}/careers`
   - `https://www.{domain}/jobs`
4. **Verification** — must return HTTP 200 and page must contain job-related text ("job", "career", "position", "opening", "apply"). Filters out redirect-to-homepage false positives.
5. **On success** — set `careers_url` in DB. Do **not** set `resolve_status='resolved'` yet (that happens after ATS detection completes; see Pipeline Flow section).
6. **On failure** — leave `careers_url` as None, increment `resolve_attempts`, don't mark as `failed` (company is still reachable via JobSpy search). If `resolve_attempts` reaches 3, set `resolve_status='failed'` to avoid re-probing on every cycle.

Up to 3 concurrent probes using `quarry/http.py` client, 5s timeout per probe.

## ATS Detector

Detects which ATS powers a company's careers page.

**Detection strategy:**

1. **Skip if `ats_type` already set** to a known ATS — `"unknown"` means "not yet detected", while `"generic"` means "resolved, no specific ATS" and is also skipped
2. **Skip if no `careers_url`** — can't detect without a page
3. **URL pattern matching (fast, no HTTP request):**
   - `boards.greenhouse.io/{slug}` → `greenhouse`, slug extracted
   - `boards-api.greenhouse.io/v1/boards/{slug}` → `greenhouse`, slug extracted
   - `jobs.lever.co/{slug}` → `lever`, slug extracted
   - `jobs.ashbyhq.com/{slug}` → `ashby`, slug extracted (NOTE: `ashbyhq.com` substring match is intentionally limited to `jobs.ashbyhq.com` subdomain only, not bare `ashbyhq.com`, to avoid false positives on non-job pages)
4. **HTML signature detection (if URL doesn't match):**
   - Greenhouse: references to `boards.greenhouse.io`, Greenhouse-specific CSS/JS
   - Lever: links to `jobs.lever.co`, Lever branding meta tags
   - Ashby: references to `jobs.ashbyhq.com`
5. **If no ATS detected** — set `ats_type = "generic"` (routes to `CareersPageCrawler`). This is a resolved state, not "pending" — the detector will skip it on future runs.
6. **Update DB** — set `ats_type`, `ats_slug`, `resolve_status = 'resolved'`

**Re-detection:** If ATS detection rules improve or a company's `careers_url` changes, use `python -m quarry.resolve --company "Name" --redetect-ats` to force re-detection. This resets `ats_type` to `"unknown"` before running the detector on that company.

**Slug extraction rules:**
- `boards.greenhouse.io/takeda` → `ats_slug = "takeda"`
- `jobs.lever.co/NimbleAI` → `ats_slug = "NimbleAI"`
- `jobs.ashbyhq.com/cognition` → `ats_slug = "cognition"`

## Database Changes

Add to `companies` table:
- `resolve_status TEXT DEFAULT 'unresolved'` — values: `unresolved`, `resolved`, `failed`
- `resolve_attempts INTEGER DEFAULT 0`

Update `Company` model to include `resolve_status` and `resolve_attempts` fields.

Ensure `db.update_company()` method exists and persists all fields.

**Semantics of `resolve_status`:**
- `unresolved` — no resolver has made progress yet, or a partial step succeeded (domain found but no careers URL yet)
- `resolved` — all applicable resolvers have completed (domain found, careers URL found, ATS detected)
- `failed` — domain resolution failed after exhausting attempts (see backoff below)

**`resolve_attempts` rules:** Each resolver step increments `resolve_attempts` on failure. If `resolve_attempts >= 3`, set `resolve_status='failed'`. This prevents re-probing doomed domains on every cycle. Count resets to 0 when any step succeeds.

**Migration for existing companies:** Add the two new columns with their defaults (`unresolved`, `0`). Existing companies will automatically be picked up by `resolve_unresolved()` on next `run_once()`. No data migration needed beyond the `ALTER TABLE`.

## CLI

**Resolve command:**
```
python -m quarry.resolve                # Resolve all unresolved companies (resolve_status='unresolved')
python -m quarry.resolve --retry-failed  # Also retry previously failed companies
python -m quarry.resolve --company "Takeda Pharmaceuticals"  # Single company by name
python -m quarry.resolve --redetect-ats  # Re-run ATS detection on companies with ats_type='generic'
```

Selection rules:
- Default: processes companies where `resolve_status='unresolved'`
- `--retry-failed`: also includes companies where `resolve_status='failed'` (resets `resolve_attempts` to 0 before retrying)
- `--redetect-ats`: resets `ats_type` to `"unknown"` on companies with `ats_type='generic'` before running detection

**Add-company command** (in `quarry/store`; see company-cli-design.md for full CLI spec):
```
python -m quarry.store add-company --name "Takeda Pharmaceuticals" --domain "takeda.com"
python -m quarry.store add-company --name "Takeda Pharmaceuticals"  # domain auto-resolved
```

The `add-company` command:
1. Inserts the company into the DB with provided fields (defaults: `active=True`, `crawl_priority=5`, `ats_type="unknown"`, `added_by="cli"`, `resolve_status="unresolved"`, `resolve_attempts=0`)
2. If `--careers-url` is provided:
   - Validates the URL has a scheme (`http`/`https`) and a hostname (no private/internal IPs)
   - Runs inline URL-pattern ATS detection (phase 1 only) for instant feedback
   - If phase 1 matches → sets `ats_type` and `ats_slug`, sets `resolve_status='resolved'`
   - If phase 1 finds nothing → leaves `ats_type="unknown"`, `resolve_status` stays `"unresolved"`; the full pipeline will run HTML detection later
3. If `--careers-url` is **not** provided, runs the full resolve pipeline (domain → careers_url → ATS detection)
4. If `--domain` is provided, validates it's a plausible domain (no private IPs, has a TLD) and skips domain resolution

## `run_once` Integration

In `quarry/agent/scheduler.py`, `run_once()` calls `resolve_unresolved(db)` before the crawl loop:

```python
def run_once(db: Database) -> dict:
    from quarry.resolve import resolve_unresolved
    resolve_unresolved(db)

    # existing crawl logic unchanged
    companies = db.get_all_companies(active_only=True)
    ...
```

This ensures newly JobSpy-created companies are resolved before each crawl cycle.

## Future Work

- **Web search domain resolution** — for companies where guess-and-probe fails (non-.com domains, abbreviations, government labs). Issue to be filed.
- **Rate limiting** — the shared HTTP client can be extended with per-domain rate limiting
- **LLM-based resolution** — use Bedrock/OpenRouter to resolve ambiguous cases (higher accuracy, cost tradeoff)