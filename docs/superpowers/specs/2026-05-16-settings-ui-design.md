# Settings UI — Design Spec

**Date:** 2026-05-16
**Status:** Refined (3 iterations, 2 models)

## Goal

Add a web UI for managing all user-facing search configuration. Currently these settings are scattered across `config.yaml` (read-only, restart required) and the database (seed-only). Move them all to a unified Settings page in the existing Flask UI, with `config.yaml` serving as factory defaults that the database can override at runtime.

## Architecture

```
config.yaml (factory defaults)
        │
        ▼
UserSettingsService ──reads/writes──► user_settings table (per-user overrides)
        │
        ├──► Flask routes (/settings GET/POST)
        │       │
        │       ▼
        │    Jinja2 templates (server-rendered, no JS framework)
        │
        └──► Scheduler (run_once) — uses service for runtime config
```

### Key Principle

All user-facing settings move into the DB's existing `user_settings` key-value table, serialized as JSON where they're complex. `config.yaml` becomes the factory default — values the DB falls back to when no user override exists. No settings are written back to `config.yaml` from the UI.

## Settings Covered (8 sections)

| #   | Section                | Current Home                    | DB Key                   | Type                                                 |
| --- | ---------------------- | ------------------------------- | ------------------------ | ---------------------------------------------------- |
| 1   | Search Queries         | `user_search_queries` table     | (separate table)         | rows with active/reason                              |
| 2   | Ideal Role Description | `user_settings` + `config.yaml` | `ideal_role_description` | text                                                 |
| 3   | Similarity Threshold   | `config.yaml`                   | `similarity_threshold`   | float (0.0–1.0, step 0.05)                           |
| 4   | Keyword Blocklist      | `config.yaml` filters           | `keyword_blocklist`      | JSON `{keywords:[], passlist:[]}`                    |
| 5   | Title Keywords         | `config.yaml` filters           | `title_keywords`         | JSON `{keywords:[]}`                                 |
| 6   | Company Filter         | `config.yaml` filters           | `company_filter`         | JSON `{allow:[], deny:[]}`                           |
| 7   | Location Filter        | `config.yaml` filters           | `location_filter`        | JSON (full LocationFilterConfig)                     |
| 8   | JobSpy Settings        | `config.yaml`                   | `jobspy_config`          | JSON `{sites:[], results_wanted:int, hours_old:int}` |

### What stays in config.yaml only

Infrastructure and backend-only settings — never shown in the UI:

- `db_path`, `seed_file`
- `llm_provider`, `aws_region`, `aws_profile`, `openrouter_api_key`, `openrouter_model`
- `openai_api_key`, `embedding_model`, `embedding_provider`
- `max_retries`, `retry_base_delay`, `max_concurrent_per_host`, `request_timeout`, `max_response_bytes`, `max_redirects`
- `ui_host`, `ui_port`, `ui_debug`
- `digest_time`, `crawl_hour`, `crawl_schedule_cron`, `careers_crawl_cron`, `reflection_after_crawl`

## New Module: `quarry/settings_service.py`

**Why `settings_service.py` and not `settings.py`:** `quarry/config.py` already exports a module-level `settings` variable (`settings = load_config()`). Using `quarry/settings.py` would create a confusing pair: `quarry.config.settings` vs. `quarry.settings`. Naming the new module `settings_service.py` avoids this ambiguity.

### `UserSettingsService`

A class that provides typed access to user settings with config.yaml fallback.

```python
class UserSettingsService:
    def __init__(self, db: Database, user_id: int = 1):
        ...

    # Typed accessors — each returns the effective value (DB override or config default)
    def get_ideal_role_description(self) -> str: ...
    def set_ideal_role_description(self, text: str) -> None: ...  # also recomputes embedding

    def get_similarity_threshold(self) -> float: ...
    def set_similarity_threshold(self, value: float) -> None: ...

    def get_keyword_blocklist(self) -> KeywordBlocklistConfig: ...
    def set_keyword_blocklist(self, config: KeywordBlocklistConfig) -> None: ...

    def get_title_keywords(self) -> TitleKeywordConfig: ...
    def set_title_keywords(self, config: TitleKeywordConfig) -> None: ...

    def get_company_filter(self) -> CompanyFilterConfig: ...
    def set_company_filter(self, config: CompanyFilterConfig) -> None: ...

    def get_location_filter(self) -> LocationFilterConfig: ...
    def set_location_filter(self, config: LocationFilterConfig) -> None: ...

    def get_jobspy_config(self) -> dict: ...
    def set_jobspy_config(self, sites: list[str], results_wanted: int, hours_old: int) -> None: ...
```

**Implementation notes:**

- Reads all `user_settings` rows for the user once (single query), caches for request lifetime
- For each getter: if key exists in DB, deserialize and return; otherwise return `config.yaml` default
- For setter: serialize if complex, write to `user_settings` (upsert), invalidate cache
- `set_ideal_role_description` calls `quarry.pipeline.embedder.set_ideal_embedding()` after writing the text. **Do not** separately write the description text via `save_user_setting()` — `set_ideal_embedding()` already saves both the embedding (hex) and the description text to the `user_settings` table in a single call. Double-writing creates a race condition between the two writes.
- **IMPORTANT:** `get_location_filter()` must call `LocationFilterConfig.normalize_config()` after deserializing from JSON. `LocationFilterConfig` uses Pydantic `PrivateAttr` for `_resolved_cities`, `_resolved_states`, `_resolved_target_coords`, etc. — these are populated by `normalize_config()` (which resolves city/state names to lat/lon via geonamescache). Without this call, location filtering silently passes all postings. Same applies to `FiltersConfig.normalize_config()` when constructing the full filter chain.

### JSON Serialization for Complex Types

- `KeywordBlocklistConfig` → `{"keywords": [...], "passlist": [...]}`
- `TitleKeywordConfig` → `{"keywords": [...]}`
- `CompanyFilterConfig` → `{"allow": [...], "deny": [...]}`
- `LocationFilterConfig` → full dict with `target_location`, `accept_remote`, `nearby_radius`, `accept_states`, `accept_regions`
- `jobspy_config` → `{"sites": [...], "results_wanted": N, "hours_old": N}`

## Scope: Similarity Threshold Filter

The `similarity_threshold` setting is currently read by `embed-ideal` CLI but is **not enforced in the runtime crawl pipeline** — `quarry/pipeline/filter.py:FILTER_STEPS` does not include a similarity threshold check, and the scheduler's `_process_posting()` passes all postings through regardless of cosine similarity score.

**Why it can't go in `FILTER_STEPS`:** The filter pipeline runs **before** embedding computation in `_process_posting()` (`quarry/agent/scheduler.py:197-227`). Each `FilterStep.check()` receives `(raw, posting, parse_result, company_name, config)` — no embedding or similarity score is available at filter time. Adding a similarity filter to `FILTER_STEPS` would require restructuring the entire function (embed before filter, defeating the performance purpose of pre-filtering).

**Approach:** Apply the threshold as a **WHERE clause in the postings read path** — specifically in `Database.get_postings_with_scores()` (`quarry/store/db.py:880-1060`). Postings with `similarity_score < threshold` are excluded from results. The `UserSettingsService.get_similarity_threshold()` provides the value; `get_postings_with_scores()` filters by it.

**Threshold scope:**

- Applies to **all postings views** (new, seen, applied, rejected, archived) — not just "new"
- **`threshold = 0` means no filter** — the WHERE clause is conditional, only active when `similarity_threshold > 0`. Since `get_postings_with_scores()` uses `func.coalesce(ORMSimScore.similarity_score, 0.0)`, a threshold of 0 would otherwise hide unscored postings
- **UI shows a note** when threshold > 0 — e.g., "Showing {n} postings (similarity ≥ {threshold})" — so the user knows filtering is active

## Scheduler Integration

`quarry/agent/scheduler.py` — `run_once()` currently uses `settings.jobspy_sites`, `settings.jobspy_results_wanted`, `settings.jobspy_hours_old`, `settings.filters`, and `settings.ideal_role_description` (via `_ensure_ideal_embedding`). Replace these with `UserSettingsService` calls:

```python
ss = UserSettingsService(db, user_id)
# Instead of: settings.filters
filters_config = FiltersConfig(
    keyword_blocklist=ss.get_keyword_blocklist(),
    title_keyword=ss.get_title_keywords(),
    company_filter=ss.get_company_filter(),
    location_filter=ss.get_location_filter(),
)
# Normalize location filter (resolves city/state names to lat/lon)
filters_config.normalize_config()
# Instead of: client = JobSpyClient()
jsc = ss.get_jobspy_config()
client = JobSpyClient(sites=jsc["sites"], results_wanted=jsc["results_wanted"], hours_old=jsc["hours_old"])
```

`_ensure_ideal_embedding()` already reads from DB via `get_ideal_embedding()` — no change needed for the embedding itself, only the description text. The signature changes from `_ensure_ideal_embedding(db, user_id)` to `_ensure_ideal_embedding(db, user_id, ss: UserSettingsService)`. Passing the service explicitly avoids a second DB query for user settings (the caller already has the service instance).

`_crawl_search_queries()` at `quarry/agent/scheduler.py:148-150` currently creates `JobSpyClient()` with no arguments (falling back to `settings.jobspy_*` defaults). This function must also accept the service-derived JobSpy config so search queries use user-configured sites/results/hours. Both `JobSpyClient()` call sites (company crawl and search crawl) are updated:

```python
# In run_once() — build service once, pass to both paths
ss = UserSettingsService(db, user_id)

# Company crawl path:
jsc = ss.get_jobspy_config()
client = JobSpyClient(sites=jsc["sites"], results_wanted=jsc["results_wanted"], hours_old=jsc["hours_old"])

# Search query crawl path (inside _crawl_search_queries):
def _crawl_search_queries(db, user_id, ss):
    # ...
    jsc = ss.get_jobspy_config()
    client = JobSpyClient(sites=jsc["sites"], results_wanted=jsc["results_wanted"], hours_old=jsc["hours_old"])
```

## UI Design

### Navigation

Add "Settings" tab to the existing nav bar in `base.html`:

```
[Postings]  [Companies]  [Settings]  [Agent Log]
```

### Layout: Tabbed Sidebar

- **Left sidebar** (200-220px): Vertical list of 8 section labels. Active section is highlighted. Clicking switches the main content area.
- **Main content area** (remaining width): Shows the active section's form. Each section has its own Save button.
- Section state is maintained via `?section=` query parameter. POST redirects preserve it.

### Section Orders and Mockups

1. **Search Queries** — Table of active queries with "Retire" links (each is a mini-form POST). Inline form at bottom to add new query (text input + optional reason). Retired queries toggleable via tab.
2. **Ideal Role Description** — Large textarea (full width, ~8 rows). Save button.
3. **Similarity Threshold** — Number input (0.0–1.0, step 0.05). Current value shown. Save button.
4. **Keyword Blocklist** — Two textareas (one per line): blocklist keywords, passlist keywords. Help text explains format. Save button commits both.
5. **Title Keywords** — Single textarea (one keyword per line). Save button. **Important:** This is a **whitelist** (must-have filter) — if any keywords are configured, a posting's title MUST contain at least one of them or it will be rejected. This is the opposite of the Keyword Blocklist (which blocks matches). The UI must clearly label this as "Required Title Keywords" with help text explaining the whitelist behavior.
6. **Company Filter** — Two textareas: "Only allow these companies" and "Deny these companies" (one per line). Save button. If the Allow list is non-empty, **only** postings from those companies pass — all others are blocked. The Deny list blocks specific companies regardless. The UI must label the sections clearly to communicate whitelist vs. blacklist semantics.
7. **Location Filter** — Target cities textarea (one per line), "Accept Remote" checkbox, nearby radius number input, accept states textarea, accept regions textarea. Save button.
8. **JobSpy Settings** — Checkboxes for each site (indeed, glassdoor, google, zip_recruiter, linkedin). Number input for results_wanted and hours_old. Save button. Site names are validated against the known set in `SITE_NAME_TO_SOURCE_TYPE` (`quarry/crawlers/jobspy_client.py`).

**Why textareas over tag chips:** Tag chips require JavaScript for add/remove interactions on the same page. With no-JS and per-section save, textareas (one item per line) are the natural pattern — edit the list, click Save. This keeps the implementation simple and consistent with the existing UI's server-rendered approach. Tag chips can be added later as a progressive enhancement with htmx or a SPA.

### Save Behavior

**Per-section save**: Each section has its own Save button (POSTs to its dedicated route). Changes are independent — editing keyword blocklist doesn't risk losing unsaved role description edits. After save, flash message confirms success and user stays on the same section.

### Routes

```
GET  /settings                         → render settings page (first section active)
POST /settings/queries/add             → add search query
POST /settings/queries/<id>/retire     → retire (set active=false)
POST /settings/role-description        → save + recompute ideal embedding
POST /settings/similarity              → save threshold
POST /settings/blocklist               → save keyword blocklist JSON
POST /settings/title-keywords          → save title keywords JSON
POST /settings/company-filter          → save company filter JSON
POST /settings/location                → save location filter JSON
POST /settings/jobspy                  → save JobSpy config JSON
```

All POST routes:

- Flash success message
- Redirect to `url_for('ui.settings', section='section-name')`
- On error, flash error and re-render with submitted values

### Template

New file: `quarry/ui/templates/settings.html`

- Extends `base.html`
- Renders sidebar from a list of `(section_id, label, icon)` tuples
- Includes section-specific partials inline (not separate template files — keeps it simple for now)
- Uses the existing `style.css` patterns (`.card`, `.badge`, `.small` buttons, etc.)
- Adds minimal new CSS for the sidebar layout (flex container, `.sidebar`, `.settings-main`)

### No JavaScript

The tab switching works via full page loads (link with `?section=` param). The sidebar is just styled `<a>` tags. No AJAX, no htmx, no Alpine.js — consistent with the existing UI's approach.

## Files Changed

| File                                | Change                                                                                                                                                                                      |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `quarry/settings_service.py`        | **New** — `UserSettingsService` class                                                                                                                                                       |
| `quarry/store/db.py`                | Add `deactivate_search_query(query_id, user_id, retired_reason=None)` and `get_all_search_queries(user_id)`; add `similarity_threshold` filter to `get_postings_with_scores()` WHERE clause |
| `quarry/pipeline/filter.py`         | No changes — similarity threshold is applied at read time, not as a filter step                                                                                                             |
| `quarry/ui/routes.py`               | Add 9 new routes for settings                                                                                                                                                               |
| `quarry/ui/templates/settings.html` | **New** — settings page template                                                                                                                                                            |
| `quarry/ui/templates/base.html`     | Add "Settings" nav link                                                                                                                                                                     |
| `quarry/ui/static/style.css`        | Add sidebar layout + settings form styles                                                                                                                                                   |
| `quarry/agent/scheduler.py`         | Replace `settings.*` with `UserSettingsService` calls; pass service to `_ensure_ideal_embedding()`                                                                                          |
| `tests/test_settings_service.py`    | **New** — service unit tests (including normalize_config round-trip)                                                                                                                        |
| `tests/test_settings_ui.py`         | **New** — route integration tests                                                                                                                                                           |

## What Doesn't Change

- No database migrations — uses existing `user_settings` and `user_search_queries` tables
- No new Python dependencies
- No changes to `config.yaml` format (existing fields remain as factory defaults)
- No changes to `quarry/pipeline/embedder.py` (already has `set_ideal_embedding`)
- No changes to `quarry/crawlers/jobspy_client.py` (already accepts constructor params)
- Postings, Companies, Agent Log pages untouched
- Labeling workflow untouched
- Scan/Retrain buttons untouched

## Future REST API Migration Path

When moving to a SPA + dedicated REST API:

1. The `UserSettingsService` is already a clean Python class — wrap in `jsonify()` routes
2. Each POST route gets a parallel `GET /api/settings/<key>` JSON endpoint
3. The Jinja2 template gets replaced by a SPA calling those API routes
4. No data migration needed — same DB tables, same service layer

## Edge Cases

- **Empty blocklist/title keywords**: Empty textarea → `[]` is valid — no filtering applied
- **Location filter with only remote checked**: Valid — all remote postings pass, no city filtering
- **Empty ideal role description**: Embedding not computed, similarity score is 0.0 for all postings until set
- **Duplicate search query**: DB UNIQUE constraint on `(user_id, query_text)` — flash "Query already exists"
- **Rapid saves**: Per-section POST means no conflicts between sections. Within a section, last write wins.
- **Scheduler running during edit**: Scheduler reads via `UserSettingsService` which does a fresh DB query each cycle — picks up changes on next `run_once()`
- **Unsaved changes on section switch**: Navigating to a different sidebar section without saving discards in-progress edits. This is acceptable for a server-rendered no-JS form — the per-section Save button is the explicit commit point. A future SPA version would add `beforeunload` or auto-save.
- **Textarea parsing**: Blank lines in textareas are stripped. Leading/trailing whitespace per line is stripped. Case is preserved (matching is case-insensitive at filter time).
- **LocationFilterConfig round-trip**: `LocationFilterConfig` uses Pydantic `PrivateAttr` for `_resolved_cities` and related fields. When serialized to JSON for DB storage, only public fields are stored. On deserialization from DB, `UserSettingsService.get_location_filter()` must call `.normalize_config()` to re-resolve city/state names to lat/lon coordinates. This is called automatically in the getter.
- **Embedding failure on save**: `set_ideal_role_description` calls `set_ideal_embedding()` which loads the sentence-transformers model. If model loading fails, the service should catch the exception and flash an error message rather than letting a 500 propagate. The description text is still saved to DB; only the embedding computation fails.
- **Glassdoor default**: The `Settings` class default at `quarry/config.py:120-125` includes `glassdoor` in `jobspy_sites`, but `config.yaml` does not. The Settings UI should display the effective defaults from the `Settings` class (which includes glassdoor), since the service falls back to `quarry.config.settings` when no DB override exists.
- **`user_profile` not in scope**: The `user_profile` field (background/target-roles/dealbreakers) is an LLM enrichment config that currently has no runtime consumer. It is intentionally excluded from v1 of the Settings UI; add it when LLM enrichment is implemented.
- **Similarity threshold note in UI**: When `similarity_threshold > 0`, the postings page should display a note indicating that low-similarity postings are filtered out. Unscored postings (`similarity_score = 0.0`) are also hidden since they have no meaningful similarity to the ideal role.
