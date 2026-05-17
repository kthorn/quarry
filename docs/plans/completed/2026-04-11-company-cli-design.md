# Company CLI Design

## Overview

Add CRUD commands for managing companies to the `quarry.store` CLI. The key feature is automatic ATS type and slug detection from careers URLs.

## Commands

All commands under `python -m quarry.store`.

### `add-company`

```
python -m quarry.store add-company \
  --name "CoreWeave" \
  --careers-url https://coreweave.com/careers \
  [--domain coreweave.com] \
  [--crawl-priority 6] \
  [--added-reason "GPU cloud infra"] \
  [--ats-type generic] \
  [--active]
```

- `--name` is required; all other fields optional
- When `--careers-url` is provided and `--ats-type` is **not**, auto-detect ATS type and slug via URL pattern matching (phase 1 only; full detection runs in the resolve pipeline)
- Explicit `--ats-type` overrides detection; `--ats-slug` can override the detected slug
- If `--careers-url` is **not** provided, runs the full resolve pipeline (domain → careers_url → ATS detection) after inserting the company
- Default values match the `Company` model: `active=True`, `crawl_priority=5`, `ats_type=unknown`, `added_by=cli`
- Prints the created company ID on success

### `list-companies`

```
python -m quarry.store list-companies [--active-only] [--format table|json]
```

- Default format is `table` (human-readable columns)
- `--active-only` filters to `active=True` (default shows all)
- `--format json` outputs JSON for scripting

### `update-company`

```
python -m quarry.store update-company ID [--name ...] [--careers-url ...] ...
```

- Takes a company ID as positional argument
- Updates only the fields passed as flags
- When `--careers-url` is changed and `--ats-type` is **not** provided, re-runs ATS auto-detection (URL pattern matching only; full detection runs in resolve pipeline)
- Explicit `--ats-type` overrides detection

### `deactivate-company`

```
python -m quarry.store deactivate-company ID
```

Sets `active=False`. Preserves all other fields.

### `activate-company`

```
python -m quarry.store activate-company ID
```

Sets `active=True`.

## ATS Auto-Detection

The `detect_ats(url)` function lives in `quarry/resolve/ats_detector.py` (shared with the resolver pipeline; imported by the CLI).

It operates in two phases:

1. **URL pattern matching** (fast, no HTTP):
   | URL pattern | ats_type | ats_slug |
   |-------------|----------|----------|
   | `boards.greenhouse.io/{slug}` | greenhouse | `{slug}` |
   | `boards-api.greenhouse.io/v1/boards/{slug}` | greenhouse | `{slug}` |
   | `jobs.lever.co/{slug}` | lever | `{slug}` |
   | `jobs.ashbyhq.com/{slug}` | ashby | `{slug}` |

2. **HTML signature detection** (if no URL pattern matches; fetches the page):
   - Greenhouse: references to `boards.greenhouse.io`, Greenhouse-specific CSS/JS
   - Lever: links to `jobs.lever.co`, Lever branding meta tags
   - Ashby: references to `jobs.ashbyhq.com`
   - If no ATS detected → `ats_type="generic"`, `ats_slug=None`

Slug extraction: strips trailing path segments (e.g. `/jobs`, `/careers`), query params, and trailing slashes, then takes the relevant path segment.

When `--careers-url` is provided to `add-company` or `update-company`, only phase 1 (URL pattern matching) runs inline for instant feedback. The full 2-phase detection runs as part of the resolve pipeline (see company-resolver-design.md).

The value `"generic"` means "resolved, no specific ATS detected" — it is a known result, not a pending state, so the detector skips companies with `ats_type="generic"`.

## File Changes

1. **New**: `quarry/resolve/ats_detector.py` — `detect_ats(url)` function (URL pattern matching + HTML signature detection)
2. **Modified**: `quarry/store/__main__.py` — add `add_company`, `list_companies`, `update_company`, `deactivate_company`, `activate_company` commands
3. **No changes**: existing `Database` methods already support all required operations (`insert_company`, `update_company`, `get_all_companies`, `get_company`) — note: new `resolve_status` and `resolve_attempts` columns from the resolver spec are handled by the DB migration there

## Design Decisions

- **No delete command**: deactivation preserves FK references to job_postings
- **`list-companies` uses existing `get_all_companies`/`get_company`**: no new DB methods needed
- **`update_company` requires explicit ID**: no fuzzy matching — CLI is precise
- **Detection is a pure function for URL patterns**: the first phase (URL pattern matching) requires no network calls; the second phase (HTML signatures) fetches the page via `quarry/http.py`
- **`added_by` defaults to `"cli"`**: distinguishes CLI-added companies from seed data (`"seed"`)
- **`ats_type="generic"` is a resolved state**: means "no specific ATS detected", not pending — the detector skips it