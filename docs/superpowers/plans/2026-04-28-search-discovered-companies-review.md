## Plan Review: Search-Discovered Companies

**Review date:** 2026-04-29  
**Codebase commit:** HEAD  
**Plan document:** `docs/superpowers/plans/2026-04-28-search-discovered-companies.md`

---

### Critical (blockers)

#### 1. Multi-user schema prerequisite is **not implemented**
The plan states: *"This plan assumes the multi-user schema rebuild has been completed."* It is not. The actual `quarry/store/schema.py` (line 1+) contains **no** `user_watchlist`, `user_posting_status`, or `users` tables. The `companies` table still carries per-user columns (`active`, `crawl_priority`, `notes`, `added_by`, `added_reason`). Consequently:
- `models.UserWatchlistItem` does not exist (`quarry/models.py` line 1+)
- `db.upsert_watchlist_item()`, `db.get_watchlist_item()`, `db.get_watchlist_companies()` do not exist (`quarry/store/db.py` line 1+)
- `db._seed_default_user()` does not exist

**Impact:** Every Task 2–5 code block in the plan references non-existent schema, models, and DB methods. Implementing the plan as-written will produce `ImportError` and `AttributeError` on first run.

#### 2. Plan reproduces the `site_name` → KeyError bug
Both the current code (`quarry/crawlers/jobspy_client.py:77`) and the plan reference `row.get("site_name")`. JobSpy returns the column as **`site`**, not `site_name`. Verified empirically:
```
Columns: ['id', 'site', 'job_url', 'job_url_direct', ...]
site: indeed
site_name: COLUMN NOT FOUND
```
This causes all source types to silently fall back to `"indeed"`.

#### 3. Plan reproduces the `job_id` → empty `source_id` bug
Current code and plan both reference `row.get("job_id")` (`quarry/crawlers/jobspy_client.py:101`). JobSpy returns the column as **`id`**. `source_id` is therefore always `""` for JobSpy rows.

#### 4. `_safe_str` already exists; plan treats it as new
`quarry/crawlers/jobspy_client.py:109` already defines `_safe_str` and uses it for `company`, `title`, `url`, `description`, `location`, and `job_id`. The plan’s Task 1 writes failing tests for a method that **already passes** and would overwrite the existing implementation. The commit message also claims to *"Add _safe_str helper"*, which is misleading.

#### 5. Breaking `company_resolver` signature change not fully coordinated
The plan changes the callback signature from `Callable[[str], Company]` to `Callable[[str, JobSpyCompanyHints], Company]`. The existing inline closure in `quarry/agent/scheduler.py:86` (`company_resolver(name: str) -> Company`) and the `JobSpyClient.fetch` docstring both use the old signature. The plan updates scheduler.py but does not flag that this is a **public API break** for any other callers or tests.

#### 6. `_extract_domain` contains a subtle string-stripping bug
Plan’s `_extract_domain` uses `parsed.hostname.lower().lstrip("www.")`. `str.lstrip` strips any combination of the characters `'w'`, `'.'`, `'w'`, `'.'` from the left, so `"wwww.example.com"` becomes `"example.com"` but `"ww2.example.com"` becomes `"2.example.com"`. Should use `removeprefix("www.")`.

---

### Important (gaps)

#### 7. `build_careers_url()` misses `job-boards.greenhouse.io` pattern
The plan’s `_detect_ats_from_url` includes `job-boards\.greenhouse\.io/([^/]+)` (used by DeepMind in seed data: `job-boards.greenhouse.io/deepmind`), but `JobSpyCompanyHints.build_careers_url()` only checks `ats_type_hint == "greenhouse"` and returns `boards.greenhouse.io/{slug}`, omitting the `job-boards` subdomain. This creates a mismatch between detected ATS and generated careers URL for some Greenhouse boards.

#### 8. `resolve_companies_batch` leaks HTTP clients
The plan’s `resolve_companies_batch` creates a client via `get_client()` but never calls `close_client()`. The existing `resolve_unresolved` in `quarry/resolve/pipeline.py:73` wraps resolution in `try/finally` with `await close_client()`. The new batch function breaks that lifecycle convention.

#### 9. `resolve_unresolved_sync` uses `asyncio.run()` inside a synchronous scheduler
`quarry/agent/scheduler.py` is entirely synchronous (invoked from `python -m quarry.agent run-once`). Calling `asyncio.run()` from inside a synchronous function that may already be running inside an event loop (e.g., if the scheduler is ever invoked from an async context) will raise `RuntimeError`. The existing `resolve_unresolved` is async and called explicitly with `asyncio.run()` in `__main__.py`, which is the safer pattern.

#### 10. Seed data loader sets `active=True` directly on Company model
`quarry/agent/tools.py:96` loads seed companies with `active=c.get("active", True)` and `added_by="seed"`. Under the plan’s intended multi-user schema, `active` and `added_by` should live on `user_watchlist`, not `companies`. The plan does not update `tools.py` or `seed()` to create watchlist entries, so seed data would be broken after the schema rebuild.

#### 11. No migration path from current DB to multi-user schema
The plan’s Task 6 provides SQL cleanup scripts assuming the multi-user schema already exists, but there is no migration that:
- Creates `users` and `user_watchlist` tables
- Migrates existing `companies.active` / `companies.added_reason` into `user_watchlist` rows
- Removes per-user columns from `companies`

Running the plan without the rebuild drops existing per-user state on the floor.

#### 12. `get_watchlist_companies` returns dicts, but template expects model attributes
The plan’s `get_watchlist_companies` returns `list[dict]`. The current `quarry/ui/templates/companies.html` accesses `company.name`, `company.ats_type`, etc. Passing a dict to the template will fail unless the template is updated to use `company["name"]` or the route wraps dicts back into objects. The plan’s Task 5 route does not show this conversion.

#### 13. `get_companies_by_ids` is added but never consumed
Task 4 adds `get_companies_by_ids()` with tests, but no other task references it. Unless there’s a follow-up plan, this is dead code.

#### 14. `resolve_or_create_search_company` hardcodes `user_id=1` but `run_once` has no user context
The scheduler’s `run_once` does not accept a `user_id` parameter. Hardcoding `user_id=1` in `resolve_or_create_search_company` is consistent with the schema rebuild plan, but the scheduler itself would need to pass `user_id` through from config or CLI.

---

### Minor (polish)

#### 15. Committing binary `quarry.db`
Task 6 instructs `git add quarry.db` and commits the binary SQLite file. This bloats the repo and is generally avoided; migrations/scripts are preferred.

#### 16. Missing `tests/test_jobspy_client.py`
The plan lists this as a test file but it does not exist. Creating it is fine, but the plan should note it is new.

#### 17. `Company` model defaults conflict with plan intent
`quarry/models.py:36` defines `active: bool = True` on `Company`. In the multi-user schema, this field should not exist on the shared table at all. The plan creates companies without setting `active=False`, so even if the schema still has the column, newly discovered companies default to `active=True` in the shared table.

#### 18. `_safe_str` doesn’t handle `pd.NA` vs `np.nan` consistently
The existing `_safe_str` uses `pd.isna(value)`. `pd.isna(pd.NA)` is `True`, but `pd.isna("")` is `False` while the plan tests expect empty string to return default. The existing code handles this with the `s if s else default` fallback, which is correct. The plan’s test `test_empty_string_returns_default` already passes against the existing code.

---

### Codebase Context

**Key files and their current state:**

| File | Current State | Plan Assumption |
|------|--------------|-----------------|
| `quarry/store/schema.py` | Single-user schema; `companies` has `active`, `added_by`, `added_reason` | Multi-user schema with `user_watchlist` already exists |
| `quarry/models.py` | No `UserWatchlistItem` | `UserWatchlistItem` exists |
| `quarry/store/db.py` | No watchlist CRUD methods | `upsert_watchlist_item`, `get_watchlist_item`, etc. exist |
| `quarry/crawlers/jobspy_client.py` | `_safe_str` already implemented; uses `site_name` and `job_id` (wrong column names) | Treats `_safe_str` as new; preserves wrong column names |
| `quarry/agent/scheduler.py` | `_crawl_search_queries` creates `Company(active=True)` directly | Should create inactive watchlist entries |
| `quarry/ui/routes.py` | `/companies` uses `db.get_all_companies(active_only=...)` | Should use `db.get_watchlist_companies(...)` |
| `quarry/ui/templates/companies.html` | Iterates `Company` objects | Should iterate dicts from `get_watchlist_companies` |
| `quarry/resolve/pipeline.py` | `resolve_unresolved` closes client in `finally` | New batch function omits client cleanup |
| `quarry/agent/tools.py` | Seeds `active=True` on `Company` | Needs to create `user_watchlist` entries instead |

**Verified JobSpy columns:**
- `site` (plan says `site_name`) — **wrong**
- `id` (plan says `job_id`) — **wrong**
- `company_url_direct` — **correct**
- `job_url_direct` — **correct**
- `company` — **correct**
- `title` — **correct**
- `url` — **correct**
- `description` — **correct**
- `location` — **correct**
- `date_posted` — **correct**

---

### Verified (correct)

1. **`company_url_direct` and `job_url_direct` exist in JobSpy DataFrame** — confirmed empirically via live scrape.
2. **`settings.max_concurrent_per_host` exists** — `quarry/config.py:93` defines `max_concurrent_per_host: int = 3`.
3. **`quarry/resolve/pipeline.py` exists with `resolve_company` and `resolve_unresolved`** — confirmed at lines 14 and 67.
4. **`seed_data.yaml` contains the exact company names** referenced in Task 6 cleanup SQL — confirmed.
5. **`_safe_str` already handles NaN/None/empty correctly** — verified against existing code (`quarry/crawlers/jobspy_client.py:109`).
6. **`quarry/ui/routes.py` has `/companies` and `/companies/<id>/toggle`** — confirmed; the plan’s new `/companies/<id>/activate` route would slot in naturally.
7. **ATS detection patterns are reasonable** — Greenhouse, Lever, and Ashby URL patterns match real-world job board URLs.

---

### Recommendation

**Do not execute this plan until the multi-user schema rebuild (`2026-04-28-schema-rebuild-multiuser.md`) is fully implemented, committed, and tested.** Once that prerequisite is met, this plan needs the following pre-flight fixes:

1. Fix `site_name` → `site` in `jobspy_client.py`
2. Fix `job_id` → `id` in `jobspy_client.py`
3. Remove redundant `_safe_str` from Task 1; treat Task 1 as "add domain/ATS extraction"
4. Fix `_extract_domain` to use `removeprefix("www.")` instead of `lstrip`
5. Update `build_careers_url` to handle `job-boards.greenhouse.io`
6. Ensure `resolve_companies_batch` closes the HTTP client or accepts an external one
7. Update `quarry/agent/tools.py` seed logic to create `user_watchlist` entries
8. Add `user_id` parameter to `run_once` or document the hardcoded default
9. Decide whether `get_watchlist_companies` returns models or dicts, and update the template accordingly
