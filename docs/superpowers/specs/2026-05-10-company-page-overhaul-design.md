# Company Page Overhaul with Descriptions — Design Spec

**Status:** Refined

**Date:** 2026-05-10

**Scope:** Replace the sparse companies table layout with a card-based UI, add LLM-generated company descriptions with Wikipedia + website sourcing, and enable human editing directly in the UI.

---

## 1. Motivation

The current `/companies` page renders companies as sparse HTML tables with em-dash (`—`) placeholders for missing fields. There is no way for a user to understand what a company does without visiting its website. This design adds a 2–3 line description to each company card, sourced from Wikipedia when available, falling back to the company website, and editable by the user.

---

## 2. Data Model Changes

### 2.1 New columns on `companies` table

| Column               | Type   | Nullable | Notes                                                  |
| -------------------- | ------ | -------- | ------------------------------------------------------ |
| `description`        | `TEXT` | Yes      | 2–3 line company summary                               |
| `description_source` | `TEXT` | Yes      | `wikipedia`, `website`, `manual`, `pending`, or `NULL` |

**Rationale for shared table:** Descriptions are factual company info, not user preference. A single canonical description avoids redundant LLM calls and simplifies editing.

### 2.2 Alembic migration

Generate with `alembic revision --autogenerate -m "add_company_description"`. Both columns are nullable — existing companies have `description = NULL, description_source = NULL`.

### 2.3 ORM model update

Update `quarry/store/models.py` `Company` class:

- `description: Mapped[Optional[str]] = mapped_column(Text)`
- `description_source: Mapped[Optional[str]] = mapped_column(Text)`

Add `CheckConstraint` in `__table_args__`:

```python
CheckConstraint(
    "description_source IN ('wikipedia','website','manual','pending')",
    name="ck_companies_description_source",
)
```

### 2.4 Pydantic model update

Update `quarry/models.py` `Company` (Pydantic) class with matching fields:

- `description: Optional[str] = None`
- `description_source: Literal["wikipedia", "website", "manual", "pending"] | None = None`

This ensures `insert_company()`, `update_company()`, and `get_company()` all pass the new fields through correctly.

---

## 3. Description Generation Pipeline

### 3.1 Trigger

Description generation runs:

1. **Automatically** when a new company is inserted via:
   - `python -m quarry.agent.tools seed` (loads from `seed_data.yaml`) — in `quarry/agent/tools.py:seed()`. Synchronous; acceptable for ~29 companies.
   - Search discovers a new company — in `quarry/agent/scheduler.py:resolve_or_create_search_company()`. Synchronous; runs inside scheduler background loop.
   - `python -m quarry.store add-company` CLI — in `quarry/store/__main__.py:add_company()`. Synchronous; CLI user expects to wait.
   - `POST /companies/<id>/activate` in the UI — `quarry/ui/routes.py:activate_company()`. **Deferred:** sets `description_source = 'pending'`, returns redirect immediately, and runs generation in a background thread so the HTTP request doesn't block. The UI shows "Generating..." until complete.
2. **On demand** via a "Generate description" button in the UI. Runs synchronously in the Flask request thread (single-user tool; acceptable).
3. **Via CLI** for backfilling existing companies: `python -m quarry.agent.tools backfill-descriptions`

### 3.2 Step 1: Wikipedia lookup

**API:** `GET https://en.wikipedia.org/api/rest_v1/page/summary/{title}`

- `title` = sanitized company name: strip suffixes ("Inc.", "Ltd.", "LLC", "Corp."), replace spaces with underscores
- Try exact name first; if 404, retry with common suffixes removed one at a time
- If HTTP 200: use the `extract` field (typically 1–3 paragraphs, already a clean encyclopedic summary)
- If 404 or non-200: proceed to website fallback
- Rate limit: polite (1 req/sec, no auth needed for REST API)

### 3.3 Step 2: Website fallback

- `GET https://{domain}/` with shared HTTP client (`quarry/http.py`)
- Extract visible text with `html.parser` + simple heuristics (strip `<script>`, `<style>`, `<nav>`, `<footer>`)
- Truncate to ~4,000 characters
- If domain missing or fetch fails: skip to LLM with company name only

### 3.4 Step 3: LLM summarization

**Input:**

- Company name
- Source text (Wikipedia extract or website text)
- Domain (if available)

**Prompt template:**

```
Summarize what {company_name} does in 2-3 concise sentences.
This summary helps a job seeker decide whether to prioritize applying there.
Be factual and neutral. Do not include marketing language.

Source material:
{source_text}
```

**Model:** New LLM client module `quarry/llm.py` (built as part of this plan). It reads `settings.llm_provider`, `settings.aws_region`, `settings.aws_profile`, `settings.openrouter_api_key`, and `settings.openrouter_model` from `quarry/config.py`.

Interface:

```python
def complete(prompt: str, model: str | None = None) -> str:
    """Send a prompt to the configured LLM and return the text response."""
```

Implementation:

- **Bedrock path:** Use `boto3.client("bedrock-runtime", region_name=settings.aws_region)` and `invoke_model` with `anthropic.claude-3-haiku-20240307-v1:0` (or configured model). Parse JSON response body.
- **OpenRouter path:** `POST https://openrouter.ai/api/v1/chat/completions` via `httpx` with `Authorization: Bearer {api_key}`. Use `"anthropic/claude-3-haiku"` as default model.
- **Error handling:** Catch `ClientError` (Bedrock) / `HTTPStatusError` (OpenRouter). On failure, raise `LLMError` (custom exception). Retry with `tenacity` (exponential backoff, max 3 attempts).
- **Timeout:** 30s per request.

This is the first concrete LLM client in the codebase.

**Output handling:**

- Strip leading/trailing whitespace
- Truncate to 500 characters max (safety)
- Store in `description`, set `description_source` to `wikipedia` or `website`

### 3.5 Step 4: On-demand regeneration

UI exposes a "Regenerate" button that re-runs the full pipeline. This is useful when the initial description is poor (e.g., website was a splash page with no info).

---

## 4. UI Layout Changes

### 4.1 Card-based layout (replaces tables)

Each company renders as a `.card` (existing CSS class from postings page):

```
┌─────────────────────────────────────────────────────────────┐
│  OpenAI                              [badge: Active]        │
│  openai.com  |  ATS: Ashby  |  Careers ↗                   │
│                                                             │
│  OpenAI is an American artificial intelligence research     │
│  organization developing large-scale AI systems including   │
│  GPT and Codex. [Edit] [Regenerate]                         │
│                                                             │
│  [Deactivate]                                               │
└─────────────────────────────────────────────────────────────┘
```

**Card structure:**

- **Header:** Company name (linked to careers URL if available), status badge
- **Meta line:** Domain (linked), ATS type (rendered as a badge or blank if `unknown`), Careers URL (linked, truncated with `…`)
- **Description:** 2–3 line summary, or "Generate description" button if `NULL`
- **Actions:** Activate/Deactivate/Reactivate, Edit description, Regenerate description

### 4.2 Em dash fix

Missing `domain`, `careers_url`, or `ats_type == 'unknown'` renders as blank space, not `—`.

### 4.3 Section grouping

Three sections remain — Active, Inactive, Discovered — rendered as stacked card lists. Each section has a count badge in the `<h2>`.

### 4.4 Inline description editing

- Clicking "Edit" replaces description text with a `<textarea>` (3 rows, 500-character soft limit enforced client-side, no hard DB limit)
- Save/Cancel buttons appear
- `POST /companies/<int:company_id>/description` updates the row
- Sets `description_source = 'manual'` on save
- Flash message: "Description updated for {company_name}"
- **Note:** "Regenerate" overwrites manual descriptions. This is intentional — the user can always re-edit afterward.

---

## 5. API / Route Changes

### 5.1 New routes in `quarry/ui/routes.py`

| Route                                     | Method | Handler                              |
| ----------------------------------------- | ------ | ------------------------------------ |
| `/companies/<int:company_id>/description` | `POST` | `update_description(company_id)`     |
| `/companies/<int:company_id>/regenerate`  | `POST` | `regenerate_description(company_id)` |

### 5.2 DB methods to update in `quarry/store/db.py`

- `insert_company()` — add `description` and `description_source` keyword arguments to the `ORMCompany(...)` constructor call
- `update_company()` — add `description=company.description` and `description_source=company.description_source` to the `.values()` dict
- `get_watchlist_companies()` — add `ORMCompany.description` and `ORMCompany.description_source` to the `select()` column list so templates receive them as dict keys
- `update_company_description(company_id: int, description: str | None, source: str | None) -> None` — new method for direct updates

### 5.3 New module: `quarry/resolve/description.py`

- `generate_company_description(company: models.Company) -> tuple[str, str]` — runs Wikipedia → website → LLM pipeline, returns `(description, source)`
- `fetch_wikipedia_summary(company_name: str) -> str | None`
- `fetch_website_text(domain: str) -> str | None`
- **Note on async HTTP:** `quarry/http.py` provides only `httpx.AsyncClient`. All async calls (Wikipedia + website fetch) are bundled into a single async function wrapped with `asyncio.run()`, following the pattern in `quarry/resolve/pipeline.py:resolve_company_sync()`. This avoids creating multiple event loops per company.

---

## 6. Error Handling

| Scenario                         | Behavior                                                                                                                              |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Wikipedia API down / 429         | Log warning, retry with `tenacity` (exponential backoff, max 3), then proceed to website fallback                                     |
| Website fetch fails              | Log warning, send company name only to LLM                                                                                            |
| LLM call fails                   | Leave `description = NULL`, `description_source = 'pending'`. UI shows "Generate description" button for both `NULL` and `'pending'`. |
| Existing companies pre-migration | `description = NULL`, `description_source = NULL` — treated as "not yet attempted"                                                    |
| Description exceeds 500 chars    | Truncate server-side before storing                                                                                                   |
| User edits to empty string       | Store empty string, `description_source = 'manual'` — user's choice                                                                   |

---

## 7. Testing Plan

| Test                        | Type        | Notes                                                 |
| --------------------------- | ----------- | ----------------------------------------------------- |
| Wikipedia REST API client   | Unit        | Mocked responses (hit, miss, timeout)                 |
| Website text extraction     | Unit        | Mocked HTML with scripts/nav/footer                   |
| LLM prompt construction     | Unit        | Verify prompt contains company name + source          |
| Description update endpoint | Unit        | Verify `description_source` set to `manual`           |
| Full pipeline integration   | Integration | Create company → generate description → verify stored |
| UI card rendering           | E2E         | Verify cards render, edit/save works                  |
| Alembic migration           | Integration | Apply + rollback                                      |

---

## 8. Future Work (Non-blocking)

- **Company similarity search:** Embed `description` text with sentence-transformers, store in new `company_embeddings` table, enable "Find similar companies" from the UI.
- **Batch backfill CLI:** `python -m quarry.agent.tools backfill-descriptions --all` to generate descriptions for all existing companies without one.

---

## 9. Files Modified / Created

| File                                 | Action                                                                                                   |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| `quarry/models.py`                   | Add `description`, `description_source` to Pydantic `Company`                                            |
| `quarry/store/models.py`             | Add `description`, `description_source` to ORM `Company`                                                 |
| `alembic/versions/`                  | New migration (autogenerated)                                                                            |
| `quarry/store/db.py`                 | Update `insert_company`, `update_company`, `get_watchlist_companies`; add `update_company_description()` |
| `quarry/llm.py`                      | **New** — LLM client wrapper (Bedrock/OpenRouter)                                                        |
| `quarry/resolve/description.py`      | **New** — generation pipeline                                                                            |
| `quarry/ui/routes.py`                | Add `POST /description`, `POST /regenerate`                                                              |
| `quarry/ui/templates/companies.html` | Rewrite — card layout, inline edit                                                                       |
| `quarry/ui/static/style.css`         | Minor additions (company card specifics)                                                                 |
| `quarry/agent/tools.py`              | Add `backfill-descriptions` subcommand; trigger generation in `seed()`                                   |
| `quarry/agent/scheduler.py`          | Trigger generation in `resolve_or_create_search_company()`                                               |
| `quarry/store/__main__.py`           | Trigger generation in `add_company()`                                                                    |
| `tests/`                             | New tests for pipeline, endpoints                                                                        |
