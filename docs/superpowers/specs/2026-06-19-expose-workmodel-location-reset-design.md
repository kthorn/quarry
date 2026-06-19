# Expose work_model + location-match status, and scoped DB reset

**Date:** 2026-06-19
**Status:** Approved (pending spec review)
**Context:** Early exploratory phase. The postings feed is polluted with
location/work-model mismatches that slipped through the ingest filter or
predate the current filter logic, and the UI gives no way to *see* why a
posting is there. This spec ships legibility (make the data visible) and a
scoped DB reset (clean slate). It deliberately does **not** change filter
logic, add display-time *filtering*, or touch the classifier — those are
follow-ups once the data is legible.

## Goal

1. Make every posting card show its work model (including `None` → "unknown")
   and whether its location matches the configured location filter.
2. Provide a `reset` CLI command with a `--keep-companies` mode that wipes
   posting-derived data (including labels and classifier models) while
   preserving companies, watchlist, search queries, and user settings.

## Non-goals (follow-up work)

- Changing `LocationFilter.check` logic (`None`-bypass, ANY-vs-ALL semantics).
- Display-time *filtering* (hiding mismatches). This spec only *shows* status.
- Classifier feature enrichment (separate title/body embeddings, structured
  features).
- Re-seeding companies or reloading search queries inside `reset`.

## Background: why the UI shows leaks

Filters run **once, at ingest time**, inside `scheduler._process_posting`
(`quarry/agent/scheduler.py:220`) via `FILTER_STEPS`. The `/postings` route
(`quarry/ui/routes.py:43`) calls `db.get_postings_with_scores(...)` and renders
rows directly — it applies **no** filter logic. So postings that survived an
older (or absent) filter config remain visible forever; changing the filter
today fixes future ingests but not the 1808 rows already in the DB. This spec
does not fix that gap; it makes it visible.

---

## Component 1: location-match indicator

### Behavior

On each posting card, next to the existing location/work_model badges, show a
badge indicating whether the posting matches the configured location filter:

| Status | Badge | When |
|---|---|---|
| `match` | `✓ location match` (green) | `LocationFilter.check` returns `passed=True` **and** the pass was due to a geographic match (not the remote-bypass and not the "no filter configured" early return). |
| `mismatch` | `✗ location mismatch` (red) | `LocationFilter.check` returns `passed=False`. |
| `unknown` | `? location unknown` (grey) | `LocationFilter.check` returns `passed=True` via the remote-bypass (`accept_remote` + `work_model == "remote"`) **or** via the "no filter configured" early return (`target_location`, `accept_states`, `accept_regions` all empty) **or** there are no parseable locations. |

The three-way status is required (rather than just pass/fail) because the
current filter has legitimate "pass but we're not sure why" paths — the
remote-bypass and the no-filter-configured case. Collapsing those to "match"
would paint a sea of green that hides the leaks; collapsing to "mismatch"
would flag remote postings as bad. The `unknown` bucket makes the ambiguity
visible, which is the whole point of this exploratory work.

### Implementation

Add a single helper in `quarry/pipeline/filter.py`, next to `LocationFilter`:

```python
def location_match_status(
    posting: JobPosting,
    location_filter_config: LocationFilterConfig | None,
) -> Literal["match", "mismatch", "unknown"]:
    """Classify a posting against the configured location filter.

    Reuses LocationFilter.check so the indicator always agrees with the
    ingest filter. Returns "unknown" when the filter passes for
    non-geographic reasons (remote-bypass, no filter configured) or when
    no locations are parseable.
    """
```

The helper:

1. Returns `"unknown"` immediately if `location_filter_config` is `None` or
   has no `target_location`/`accept_states`/`accept_regions` (mirrors the
   `LocationFilter.check` early return at `filter.py:152-157`).
2. Returns `"unknown"` if `posting.work_model == "remote"` and
   `config.accept_remote` (mirrors the remote-bypass at `filter.py:163-171`).
3. Re-parses `posting.location` via `parse_location`. Returns `"unknown"` if
   there are no parsed locations (mirrors `filter.py:172-173`).
4. Calls `LocationFilter().check(...)` with a synthetic `RawPosting` (only
   `.title`/`.location`/`.description` are read by `LocationFilter`) and
   returns `"match"` if `passed`, `"mismatch"` otherwise.

Step 4 is the key reuse: by the time we reach it, we've already excluded the
non-geographic pass paths, so a `passed=True` here is guaranteed to be a
genuine geographic match, and `passed=False` is a genuine mismatch. This
keeps the matching logic in exactly one place (`LocationFilter`).

`LocationFilterConfig` must be `normalize_config()`-ed before use (it resolves
the `_resolved_cities`/`_resolved_target_coords`/etc. private attrs in place).
The helper calls `normalize_config()` defensively if it hasn't been called;
`normalize_config` is idempotent (it rebuilds the sets from the public fields).

### Wiring into the route

In `postings()` (`quarry/ui/routes.py:43`):

1. After fetching `results`, load the location filter config via the existing
   `ss.get_location_filter()` call pattern (already used elsewhere in
   `routes.py:327`). Fall back to `settings.filters.location_filter` if the
   user setting is absent (same pattern as `scheduler.py:283-285`). Call
   `normalize_config()` once.
2. If a config exists, build a `JobPosting` shim per row (only `.location` and
   `.work_model` are needed) and call `location_match_status(...)`, attaching
   the result as `row["location_match"]`.
3. If no config, set `row["location_match"] = None` for every row (template
   hides the badge).

This is per-row work on a paginated result set (≤ `PER_PAGE + 1` rows), each
involving one `parse_location` call (geonamescache is in-memory) and one
`LocationFilter.check`. Cheap enough that no caching is warranted for the
page sizes in use.

### Template

In `postings_results.html`, after the existing work_model badge, add:

```html
{% if row.location_match == "match" %}
  <span class="badge badge-loc-match">✓ location match</span>
{% elif row.location_match == "mismatch" %}
  <span class="badge badge-loc-mismatch">✗ location mismatch</span>
{% elif row.location_match == "unknown" %}
  <span class="badge badge-loc-unknown">? location unknown</span>
{% endif %}
```

Hidden entirely when `row.location_match is none`.

---

## Component 2: work_model badge for `None`

### Behavior

Today `postings_results.html:8` renders the work_model badge only
`{% if row.work_model %}`. Postings with `work_model=None` (1061/1808 in the
current corpus) show no badge — the gap is invisible.

Change: render a grey `unknown` badge when `work_model` is falsy.

### Template change

```html
{% if row.work_model %}
  <span class="badge badge-{{ row.work_model }}">{{ row.work_model }}</span>
{% else %}
  <span class="badge badge-unknown">unknown</span>
{% endif %}
```

### CSS

Add `.badge-unknown` (greyscale, matching existing badge style) and the three
location-badge classes to the existing stylesheet. Reuse the existing
`.badge` base; only color differs.

---

## Component 3: `reset` CLI command with `--keep-companies`

### Command

```
python -m quarry.store reset                  # full wipe
python -m quarry.store reset --keep-companies  # keep company infrastructure
```

Added to `quarry/store/__main__.py` alongside the existing `init` /
`add-company` commands.

### What each mode touches

| Table / artifact | `--keep-companies` | full `reset` |
|---|---|---|
| `job_postings` | delete | delete |
| `job_posting_locations` | delete | delete |
| `user_similarity_scores` | delete | delete |
| `user_classifier_scores` | delete | delete |
| `user_ranking_scores` | delete | delete |
| `user_posting_state` (labels) | delete | delete |
| `user_enriched_postings` | delete | delete |
| `crawl_runs` | delete | delete |
| `quarry/models/classifier_*.pkl` | delete | delete |
| `companies` | **keep** | delete |
| `user_watchlist` | **keep** | delete |
| `user_search_queries` | **keep** | delete |
| `user_settings` (ideal role, etc.) | **keep** | delete |
| `users` (default user row) | **keep** | delete |
| `pipeline_configs` | **keep** | delete |
| `locations` (geocode cache) | **keep** | delete |

### Rationale on judgment calls

- **Labels deleted in both modes.** Labels are tied to postings; deleting
  postings orphans them. More importantly, the existing labels were made
  against a polluted feed (location-driven "not interested" marks teach the
  classifier the wrong thing now that the filter will handle location).
  Deleting them gives a clean restart; the classifier goes cold (returns 0.0)
  until ≥20 fresh labels exist. Confirmed acceptable.
- **Classifier `.pkl` models deleted in both modes.** Trained on the old
  labels; useless once labels are gone, and `ClassifierScorer._try_load_model`
  would otherwise load a stale model that disagrees with the new corpus.
- **`crawl_runs` deleted in both modes.** Reference `company_id` (not
  `posting_id`) so not technically orphaned, but their counts become
  meaningless historical noise after a clean slate.
- **`locations` kept in keep-companies mode.** Geocode cache; harmless and
  saves re-resolving on the next crawl. In full mode it's dropped as part of
  the total wipe.
- **`pipeline_configs` kept in keep-companies mode.** Pure ranking config, no
  data dependency; keeping avoids re-defaulting the ranking setup.

### Implementation

`--keep-companies` mode deletes only the posting-derived tables, via targeted
`DELETE FROM <table>` statements in dependency order (children before parents,
honoring foreign keys). Full mode uses `Base.metadata.drop_all` +
`create_all` (same as `init_db` but destructive), then re-seeds the default
user. Both modes remove `quarry/models/classifier_*.pkl` via glob, with the
path computed from `_MODELS_DIR` in `quarry/rank/train.py` (already an
absolute path) rather than a hardcoded relative path.

Both modes report what was deleted: table name → row count, and number of
`.pkl` files removed.

### Safety

- Confirmation prompt by default. The prompt names what's actually being
  deleted in the chosen mode, e.g. for `--keep-companies`:
  `"This will delete 1808 postings, 31 labels, 6 classifier models, and 137 crawl runs (keeping 29 companies, watchlist, and search queries). Type 'reset' to confirm: "`
  Counts are queried before prompting. Full mode names "all companies,
  watchlist, search queries, and settings" as also deleted.
- `--yes` flag skips the prompt (for scripted use / re-runs).
- The command refuses to run if `settings.db_path` points at a non-existent
  file (nothing to reset) — prints an error and exits non-zero.

---

## Testing

### `location_match_status` helper (`tests/test_pipeline_filter.py`)

- `match`: posting in target city → `"match"`.
- `match`: posting within `nearby_radius` but not in target city → `"match"`.
- `mismatch`: posting in a far-away single city, `work_model=None` →
  `"mismatch"` (the Irvine case).
- `unknown`: `work_model == "remote"` with `accept_remote=True` → `"unknown"`.
- `unknown`: no parseable locations (`location=None`) → `"unknown"`.
- `unknown`: no location filter configured (config is `None`) → `"unknown"`.
- `unknown`: config present but `target_location`/`accept_states`/
  `accept_regions` all empty → `"unknown"`.
- Idempotency: calling `location_match_status` does not mutate the config
  (verifies `normalize_config` is safe to call defensively).

### `work_model` badge (`tests/test_ui.py`)

- Render a row with `work_model=None` → assert `badge-unknown` span present.
- Render a row with `work_model="hybrid"` → assert `badge-hybrid` present and
  `badge-unknown` absent (no regression).

### `reset` command (`tests/test_store_cli.py`)

Use a temp DB path (not the real `quarry.db`). Seed it with a company, a
posting, a label, and a dummy `.pkl` in a temp models dir.

- `reset --keep-companies --yes`:
  - `job_postings`, `user_posting_state`, `crawl_runs` are empty.
  - `companies` row count unchanged.
  - `user_settings`, `user_search_queries` unchanged.
  - `.pkl` file removed.
  - Default user still present.
- `reset --yes` (full):
  - All tables empty (including `companies`).
  - `.pkl` file removed.
  - Default user re-seeded.
- `reset` without `--yes` declines to proceed when stdin is empty / answers
  anything other than "reset" (non-interactive guard).
- Refuses to run on a non-existent db path.

### Existing tests

All existing tests must continue to pass. No changes to `get_postings_with_scores`
query shape (the `location_match` key is added in the route, not the query), so
the query's existing tests are unaffected.

---

## Files touched

- `quarry/pipeline/filter.py` — add `location_match_status` helper.
- `quarry/ui/routes.py` — compute `location_match` per row in `postings()`.
- `quarry/ui/templates/postings_results.html` — work_model `unknown` badge +
  location-match badge.
- `quarry/ui/static/*.css` — `.badge-unknown`, `.badge-loc-match`,
  `.badge-loc-mismatch`, `.badge-loc-unknown`.
- `quarry/store/__main__.py` — add `reset` command.
- `tests/test_pipeline_filter.py` — `location_match_status` tests.
- `tests/test_ui.py` — badge render tests.
- `tests/test_store_cli.py` — `reset` command tests.
- `docs/STATUS.md` — update after implementation.

## Sequencing

1. `reset` command + tests (unblocks the actual DB reset you want to do now).
2. Component 2 (work_model `unknown` badge) — trivial, do alongside.
3. Component 1 (location-match indicator) + tests.
4. Run `python -m quarry.store reset --keep-companies`, re-seed labels over
   the fresh crawl, update `docs/STATUS.md`.
