# Per-user read-time location/work filter, ingest logging, and scoped DB reset

**Date:** 2026-06-19
**Status:** Approved (spec review round 1 applied — see changelog at bottom)
**Context:** Early exploratory phase. The postings feed carries location/work
mismatches that the *ingest* filter either let through or generated under older
filter logic, and the UI applies no filtering at read time — so leaks persist
forever regardless of config changes. This spec moves location/work filtering
to the read path (multi-user-correct), makes the filter decision visible per
posting via two badges, adds per-filter ingest logging so we can see what's
being tossed, and ships a scoped DB reset for a clean restart.

## Architectural decision: split filters by intent

Two kinds of filters serve different purposes and belong at different layers:

- **Ingest-time (universal, content-based):** `KeywordBlocklistFilter`,
  `TitleKeywordFilter`, `CompanyFilter`. Drop postings *no one* on this
  instance would want, before the expensive embedding step. Kept at ingest
  to avoid paying embedding compute on obvious spam. Unchanged from today.
- **Read-time (per-user, preference-based):** `LocationFilter`, now
  including work-model. Applied in the `/postings` query, per user. Removed
  from `FILTER_STEPS` / `_process_posting`.

**Why:** with N users having different location/work preferences, ingest-time
filtering against one user's config is wrong by construction. Moving
preference filters to read time means (a) changing preferences instantly
reclassifies the corpus without re-crawling, (b) the DB becomes a pure
superset of everyone's interest with each user's view a projection, (c) the
badges shown to a user always agree with that user's actual filter — no
display-vs-ingest divergence.

**Consequence (accepted):** postings that *would* have been location-filtered
at ingest now get embedded and stored. Storage + embedding compute go up; the
DB accumulates postings no current user wants. Kurt confirmed this is
acceptable for now. A TTL to retire stale postings is tracked separately in
GitHub issue #7.

## Goal

1. Move location + work-model filtering from ingest to read-time (per-user).
2. Show two badges per posting: work-type match and location match.
3. Add per-filter aggregate ingest logging (how many removed by each filter).
4. Provide a `reset` CLI command with `--keep-companies` mode for a clean
   restart that preserves companies, watchlist, search queries, and settings.

## Non-goals (follow-up work)

- Changing the ingest-time filters (`KeywordBlocklistFilter`,
  `TitleKeywordFilter`, `CompanyFilter`) — they stay as-is.
- TTL / retirement of stale postings (issue #7).
- Classifier feature enrichment (separate title/body embeddings, structured
  features).
- Re-seeding companies or reloading search queries inside `reset`.
- Multi-user retirement (per-user TTL). Single global TTL to start, later.

---

## Component 1: read-time location + work-model filter

### The truth table

Two user-preference inputs (both already in config, no new work-type list):

- **Accept remote?** (`accept_remote`, already on `LocationFilterConfig`)
- **Have target locations?** (implied by `target_location` being non-empty →
  means the user is open to in-person/hybrid there)

Posting inputs:

- `work_model`: `onsite` / `hybrid` / `remote` / `None`
- location: matches a target / doesn't / unparseable

A new setting controls how `work_model=None` is treated:

- **Generous** (default): assume `None` is acceptable — pass regardless of
  location. (This preserves current behavior for users with no opinion.)
- **Strict**: `None` is never acceptable on the work-type axis — fail unless
  location matches *and* the user has target locations set (i.e. treat `None`
  like an in-person posting for location purposes, but flag the work-type
  badge as a miss).

Full truth table (pass = shown by default; fail = hidden unless "show all"):

| posting work_model | location | generous None | strict None |
|---|---|---|---|
| onsite | matches | ✅ pass | ✅ pass |
| onsite | doesn't match | ❌ fail | ❌ fail |
| hybrid | matches | ✅ pass | ✅ pass |
| hybrid | doesn't match | ❌ fail | ❌ fail |
| remote | *anything* | ✅ pass (loc ignored) | ✅ pass (loc ignored) |
| None | matches | ✅ pass | ✅ pass |
| None | doesn't match | ✅ pass (generous) | ❌ fail (strict) |
| None | unparseable | ✅ pass (generous) | ❌ fail (strict) |

"Wanted work types" derived from existing config, no new list:
`wanted = ({remote} if accept_remote) ∪ ({onsite, hybrid} if target_location
set)`. So:

- "remote-only" = `accept_remote=true, no target_location`
- "in-person SF only" = `target_location=[SF], accept_remote=false`
- "either" = both set
- "neither" (no target, `accept_remote=false`) → `filter_active=False`;
  the filter is effectively off, the read path shows everything, and all
  match/miss badges are hidden (nothing to match against).

### Implementation: a single classifier function

Add `quarry/pipeline/filter.py`:

```python
class LocationMatchResult(BaseModel):
    filter_active: bool        # is any location/work preference configured?
    work_type_match: bool      # does the posting's work_model fit user prefs?
    location_match: bool       # does a parsed location hit a target?
    location_relevant: bool    # is location even considered? (False for remote / no targets)

    @computed_field
    @property
    def passes(self) -> bool:
        """Overall: should this be shown by default?"""
        if not self.filter_active:
            return True
        return self.work_type_match and (self.location_match or not self.location_relevant)

def evaluate_location_match(
    posting: JobPosting,
    config: LocationFilterConfig | None,
) -> LocationMatchResult:
    """Apply the location+work-model truth table for a user.

    This is the single source of truth for read-time filtering AND for the
    badges — the UI shows exactly what this function decided.
    """
```

`passes` is a `@computed_field` (not stored state) because it is fully
 derivable from the other four booleans; storing it separately risks drift.

Define `targets_set = bool(config.target_location or config.accept_states
or config.accept_regions)` and `filter_active = targets_set or
config.accept_remote` (when `config is None`, `filter_active=False`).

Logic:

1. **Filter off** (`not filter_active`): return `filter_active=False,
   work_type_match=True, location_relevant=False, location_match=True`.
   `passes` computes to `True` (show everything). The template hides all
   match/miss badges via the `filter_active` gate (Component 2) — nothing to
   match against.
2. **Work-type axis:**
   - `work_model == "remote"` → `work_type_match = config.accept_remote`.
   - `work_model in ("onsite", "hybrid")` → `work_type_match = targets_set`
     (in-person/hybrid wanted only if the user has targets).
   - `work_model is None` → generous: `work_type_match = True`; strict:
     `work_type_match = targets_set` (treat None like in-person).
3. **Location axis:**
   - `location_relevant = filter_active AND targets_set AND work_model !=
     "remote"`. (Remote postings ignore location; when the user has no
     targets — e.g. remote-only prefs — location is irrelevant even for an
     onsite posting, whose rejection is on the work-type axis, not location.)
   - If `not location_relevant`: `location_match = True` (don't penalize on
     an axis we're not considering).
   - If `location_relevant`: re-parse `posting.location` via `parse_location`.
     - **No parseable locations** → `location_match = False` under strict,
       `True` under generous (can't prove it's wrong, be generous). This
       pre-check is required because the shared `geographic_match` helper
       (below) is only meaningful when locations exist.
     - Otherwise `location_match = geographic_match(parse_result, config)`
       (the extracted shared helper — see "Reuse" below).
4. `passes` is computed by the `@computed_field` above.

### Reuse: extract a shared `geographic_match` helper

The city / `nearby_radius` / `accept_states` / `accept_regions` matching loop
is currently inlined in `LocationFilter.check` (`quarry/pipeline/filter.py`,
the block after the empty-`parse_result` early return). Extract it into a
module-level helper:

```python
def geographic_match(parse_result: ParseResult, config: LocationFilterConfig) -> bool:
    """True if any parsed location hits a target city / nearby_radius /
    accepted state / accepted region. Assumes parse_result.locations is
    non-empty and config has at least one target — callers gate on those."""
```

`LocationFilter.check` keeps its existing early returns (no-filter-configured,
remote bypass, empty-`parse_result`) but delegates the actual matching loop
to `geographic_match`. `evaluate_location_match` calls `geographic_match`
**directly** (after its own gating: `location_relevant`, `targets_set`,
non-remote, and non-empty parse_result).

**Why extract rather than call `LocationFilter.check` with a synthetic
`RawPosting`:** `LocationFilter.check`'s signature takes `(raw, posting,
parse_result, company_name, config)` and reads `raw.title`/`raw.location`
only in `log.debug` calls — the real matching input is `parse_result`, not
`raw`. Calling it from `evaluate_location_match` would require constructing
synthetic `RawPosting` + `JobPosting` shims purely to satisfy the signature,
AND would re-trigger `LocationFilter.check`'s own early returns
(no-filter → `passed=True`; empty-parse_result → `passed=True`), which
**contradict** `evaluate_location_match`'s strict-mode decisions and would
produce wrong badges (e.g. unparseable+strict would render `✓ location`;
remote-only-prefs+onsite would render `✓ location`). Extracting
`geographic_match` avoids the synthetic shims, eliminates the
double-handling, and keeps the geographic matching logic in exactly one
place so any future fix updates both code paths.

### New config: None-strictness

Add to `LocationFilterConfig`:

```python
class NoneStrictness(str, Enum):
    GENEROUS = "generous"   # None work_model → assume acceptable
    STRICT = "strict"       # None work_model → require location match + targets

class LocationFilterConfig(BaseModel):
    # ... existing fields ...
    none_strictness: NoneStrictness = NoneStrictness.GENEROUS
```

Default generous preserves current behavior. Editable from the Settings UI
alongside the existing location filter fields (the Settings UI already has a
Location Filter section — add a dropdown). Persisted via the existing
`UserSettingsService.set_location_filter` path.

**Settings route round-trip (must update `settings_location`,
`quarry/ui/routes.py:465`):** the current route constructs
`LocationFilterConfig(...)` with an explicit field list (`target_location`,
`accept_remote`, `nearby_radius`, `accept_states`, `accept_regions`) and does
**not** pass `none_strictness`. If left unchanged, every Location Filter save
would apply the `GENEROUS` default and silently overwrite a previously-saved
`STRICT` choice. The route MUST read `none_strictness` from `request.form`
and pass it into the `LocationFilterConfig(...)` constructor. Likewise the
GET/render side (`settings` route ~`quarry/ui/routes.py:327`) already passes
`location_f` to the template; the dropdown's `selected` attribute must
compare against `location_f.none_strictness.value` (the enum's string value,
not the enum member) to match the option's `value="strict"`/`value="generous"`.

### Read-time wiring

In `postings()` (`quarry/ui/routes.py:43`):

1. Load the location filter config (`ss.get_location_filter()` with
   `settings.filters.location_filter` fallback, same pattern as
   `scheduler.py:283-285`). `normalize_config()` once.
2. For each row in `results`, build a `JobPosting` shim (only `.location` and
   `.work_model` needed) and call `evaluate_location_match(...)`. Attach
   `work_type_match`, `location_match`, `location_relevant`, `passes` to the
   row dict.
3. **Default view: hide postings where `passes == False`.** Add a `show_all`
   query param (`/postings?show_all=1`). When `show_all` is falsy, filter the
   `results` list in Python (post-query) to rows where `passes` is true. When
   `show_all=1`, show everything with badges visible.
   - Rationale for post-query filtering in Python rather than SQL: the truth
     table needs `parse_location` per row (geonamescache, in-memory) which
     can't be pushed to SQL. Page size is small (≤ `PER_PAGE + 1`), so
     over-fetching and filtering in Python is fine. Over-fetch factor: fetch
     `per_page * K` rows (K=3 estimate) before filtering to keep pagination
     roughly correct; document the approximation in a comment.
4. Badges are rendered from the attached fields (Component 2).

**Ingest change:** remove `LocationFilter()` from `FILTER_STEPS` in
`quarry/pipeline/filter.py`. The `FILTER_STEPS` list becomes
`[KeywordBlocklistFilter(), TitleKeywordFilter(), CompanyFilter()]`. The
`LocationFilter` class stays in the module (used by
`evaluate_location_match`). Update `scheduler._process_posting` callers —
the `filters_config` still carries `location_filter` for the remaining
filters' configs but `LocationFilter` no longer runs at ingest. Existing
ingest tests that assert location-filtering-at-ingest behavior need updating
to assert read-time behavior instead.

---

## Component 2: two badges per posting

### Work-type badge

| condition | badge |
|---|---|
| `filter_active == False` and `work_model` in (remote/hybrid/onsite) | `<work_model>` (existing colored badge — factual, always shown when known) |
| `filter_active == False` and `work_model is None` | hidden (no preference configured → no match assessment) |
| `filter_active == True` and `work_model` in (remote/hybrid/onsite) and `work_type_match` | `<work_model>` (existing colored badge) |
| `filter_active == True` and `work_model is None` and `work_type_match` (generous) | `work: unknown (generous)` (grey) |
| `filter_active == True` and `not work_type_match` | `work: ✗` (red) |

Note: when `filter_active == False`, the existing colored `work_model` badge
still renders for known work models (it's factual posting info, not a
preference assessment); only the match/miss assessment is hidden. For
`work_model is None` + filter off, nothing renders.

### Location badge

| condition | badge |
|---|---|
| `not filter_active` or `not location_relevant` | hidden |
| `location_relevant` and `location_match` | `✓ location` (green) |
| `location_relevant` and `not location_match` | `✗ location` (red) |

### Template (`postings_results.html`)

Replace the existing work_model badge block with (note the `filter_active`
gate on the assessment branches — this is what distinguishes filter-off from
remote-only-prefs + None-generous, which produce identical `work_type_match`
values but must render differently):

```html
{% if row.work_model %}
  <span class="badge badge-{{ row.work_model }}">{{ row.work_model }}</span>
{% elif row.filter_active and row.work_type_match %}
  <span class="badge badge-unknown">work: unknown (generous)</span>
{% elif row.filter_active and not row.work_type_match %}
  <span class="badge badge-work-miss">work: ✗</span>
{% endif %}
{% if row.filter_active and row.location_relevant %}
  {% if row.location_match %}
    <span class="badge badge-loc-match">✓ location</span>
  {% else %}
    <span class="badge badge-loc-miss">✗ location</span>
  {% endif %}
{% endif %}
```

Trace of the previously-broken cases (now fixed by `filter_active`):

- Filter off + `work_model=None`: first branch skipped (None falsy), both
  `elif`s gated on `filter_active` (False) → nothing renders. ✓ (was wrongly
  rendering `work: unknown (generous)`.)
- Remote-only prefs + onsite posting: `work_type_match=False`, first branch
  renders `onsite` (factual), `elif` → `work: ✗`, `location_relevant=False`
  → location badge hidden. ✓ (was wrongly rendering `✓ location`.)
- Filter off + `work_model=hybrid`: first branch renders `hybrid` (factual),
  assessment branches gated off → no match/miss badge. ✓

### CSS

Add `.badge-unknown`, `.badge-work-miss`, `.badge-loc-match`, `.badge-loc-miss`
to the existing stylesheet, reusing the `.badge` base; only color differs.

---

## Component 3: per-filter ingest logging

### What

At the end of each scan run, log an aggregate breakdown of how many postings
each ingest filter removed. Today only a single `total_filtered` counter
exists (`scheduler.py:319`); the per-`skip_reason` counts are in the CSV log
but not summarized.

### Implementation

In `scheduler.run_once`:

1. Add a `Counter[str]` (`skip_reason_counts`) accumulated alongside
   `total_filtered`. Increment it with `decision.skip_reason` whenever a
   posting is filtered (both the company-crawl loop at ~`scheduler.py:404`
   and the search-results loop).
2. After both loops, log one summary line per filter:

   ```
   log.info("Ingest filter summary: %s", ", ".join(
       f"{name}={count}" for name, count in sorted(skip_reason_counts.items())
   ))
   ```

   Producing e.g. `Ingest filter summary: blocklist=12, company_deny=3,
   title_keyword=45`. Also include in the existing per-run log.
3. No CSV schema change (the per-row `skip_reason` column already exists).

`skip_reason` values are already the filter `decision.skip_reason` strings:
`blocklist`, `title_keyword`, `company_allow_skip`, `company_deny`. With
`LocationFilter` removed from ingest, `location` will no longer appear —
which is itself the point (location is no longer an ingest filter).

### Why not a structured log / metrics table

YAGNI. A single `log.info` summary line per run is enough to see what's being
tossed during exploration. If we later want trend tracking, that's a separate
metrics-table spec.

---

## Component 4: `reset` CLI command with `--keep-companies`

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
| `user_settings` (ideal role, location filter, etc.) | **keep** | delete |
| `users` (default user row) | **keep** | delete |
| `pipeline_configs` | **keep** | delete |
| `locations` (geocode cache) | **keep** | delete |

### Rationale on judgment calls

- **Labels deleted in both modes.** Labels are tied to postings; deleting
  postings orphans them. More importantly, the existing labels were made
  against a polluted feed (location-driven "not interested" marks teach the
  classifier the wrong thing now that the filter handles location at read
  time). Deleting gives a clean restart; the classifier goes cold (returns
  0.0) until ≥20 fresh labels exist. Confirmed acceptable.
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
- **`user_settings` kept in keep-companies mode.** Preserves the ideal role
  description and the location filter config (including the new
  `none_strictness` setting) — so the read-time filter works immediately
  after reset without re-configuring.

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
  deleted in the chosen mode, with live counts, e.g. for `--keep-companies`:
  `"This will delete 1808 postings, 31 labels, 6 classifier models, and 137 crawl runs (keeping 29 companies, watchlist, search queries, and settings). Type 'reset' to confirm: "`
  Full mode names "all companies, watchlist, search queries, and settings" as
  also deleted. Counts are queried before prompting.
- `--yes` flag skips the prompt (for scripted use / re-runs).
- Refuses to run if `settings.db_path` points at a non-existent file (nothing
  to reset) — prints an error and exits non-zero.

---

## Testing

### `evaluate_location_match` (`tests/test_pipeline_filter.py`)

Cover every row of the truth table:

- onsite + location matches → `passes=True`, `location_relevant=True`,
  `location_match=True`, `work_type_match=True`.
- onsite + location doesn't match → `passes=False`, `location_match=False`.
- hybrid + matches / doesn't match → same shape as onsite.
- remote + any location (including unparseable) → `passes=True` (when
  `accept_remote`), `location_relevant=False`.
- remote + `accept_remote=false` (in-person-only prefs, posting mislabeled
  remote) → `passes=False`, `work_type_match=False`, `location_relevant=False`.
  (Truth-table edge case the first draft omitted; covered by the work-type
  axis rule `work_model=="remote" → work_type_match = accept_remote`.)
- None + matches → `passes=True` (both strictnesses).
- None + doesn't match, generous → `passes=True`, `work_type_match=True`.
- None + doesn't match, strict → `passes=False`, `work_type_match=False`.
- None + unparseable, generous → `passes=True`.
- None + unparseable, strict → `passes=False`.
- Filter off (no targets, `accept_remote=false`) → `filter_active=False`,
  `passes=True`, `location_relevant=False`, badges hidden.
- Filter off + `work_model=None` → same booleans; template renders NO
  work-type badge (regression guard for the `filter_active` gate — first
  draft wrongly rendered `work: unknown (generous)` here).
- Remote-only prefs (`accept_remote=true`, no targets) + onsite posting →
  `passes=False`, `work_type_match=False`, `location_relevant=False`
  (location badge hidden — rejection is on work-type, not location).
- Remote-only prefs + `work_model=None`, generous → `filter_active=True`,
  `work_type_match=True`, `passes=True`; template renders
  `work: unknown (generous)` (distinct from filter-off+None, which renders
  nothing — this is the case the 4-boolean model couldn't distinguish).
- `evaluate_location_match` does not mutate the config (verifies
  `normalize_config` is safe to call defensively).

### Ingest change (`tests/test_scheduler.py` / `tests/test_pipeline_filter.py`)

- **Update the existing `TestFilterSteps.test_filter_steps_list_exists`**
  (`tests/test_pipeline_filter.py:682-689`), which currently asserts
  `len(FILTER_STEPS) == 4` and `isinstance(FILTER_STEPS[3], LocationFilter)`.
  After the change it must assert `len == 3` and the list is
  `[KeywordBlocklistFilter, TitleKeywordFilter, CompanyFilter]` (by class),
  with `LocationFilter` absent. This is the named breaking test.
- Audit `tests/` for any other test asserting ingest-time location filtering
  (grep `skip_reason="location"`, `LocationFilter`, ingest + location in
  `test_scheduler.py` / `test_e2e.py`); rewrite each to assert read-time
  behavior instead. List each in the implementation plan.
- A posting that the old `LocationFilter` would have rejected (e.g. Irvine,
  single remote-less location) now **passes** ingest and is stored.
  Integration test in `test_scheduler.py` or `test_e2e.py`.
- `geographic_match` helper: unit-test the extracted loop directly (city
  match, `nearby_radius` match, state match, region match, no-match) so the
  extraction is covered independently of `LocationFilter.check`.

### Read-time filter + badges (`tests/test_ui.py`)

- `/postings` default view hides a posting with `passes=False` (e.g. Irvine,
  strict mode) and shows one with `passes=True`.
- `/postings?show_all=1` shows both, with the correct badges.
- Template render: `work_model=None` + `filter_active=True` + generous →
  `badge-unknown` present.
- Template render: `filter_active=True` + `work_type_match=False` →
  `badge-work-miss` present.
- Template render: `filter_active=True` + `location_relevant=True` + match →
  `badge-loc-match`; mismatch → `badge-loc-miss`.
- **Filter off + `work_model=None` → no work-type badge AND no location badge**
  (regression guard for the `filter_active` gate; first draft rendered
  `badge-unknown` here).
- **Filter off + `work_model=hybrid` → `badge-hybrid` present, no match/miss
  badge** (factual badge survives, assessment hidden).

### Settings round-trip (`tests/test_ui.py` / `tests/test_settings_service.py`)

- Saving the Location Filter form with `none_strictness=strict` persists
  `strict` and survives a subsequent GET (no silent reset to `generous`).
- Saving any other Location Filter field (e.g. toggling `accept_remote`)
  preserves the previously-saved `none_strictness` (regression guard for the
  `settings_location` route fix).
- Template dropdown `selected` matches `location_f.none_strictness.value`.

### Ingest logging (`tests/test_scheduler.py`)

- After a scan run that filters postings, the log/output contains a
  `Ingest filter summary:` line with per-`skip_reason` counts.
- `location` does not appear in the summary (LocationFilter removed from
  ingest).

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

All existing tests must continue to pass except the **named behavior-change
break**: `TestFilterSteps.test_filter_steps_list_exists`
(`tests/test_pipeline_filter.py:682-689`), which must be updated as described
above. Any other test asserting ingest-time location filtering (found via the
grep audit) is also a behavior-change update, not a regression. All other
existing tests must pass unchanged.

---

## Files touched

- `quarry/pipeline/filter.py` — add `evaluate_location_match` +
  `LocationMatchResult`; extract `geographic_match` helper from
  `LocationFilter.check`; remove `LocationFilter` from `FILTER_STEPS` (class
  stays, `check` delegates matching to `geographic_match`).
- `quarry/config.py` — add `NoneStrictness` enum + `none_strictness` field on
  `LocationFilterConfig`.
- `quarry/ui/routes.py` — compute `evaluate_location_match` per row in
  `postings()`; `show_all` param; default-hide `passes=False`; **update
  `settings_location` to read/pass `none_strictness`** (round-trip fix).
- `quarry/ui/templates/postings_results.html` — two-badge model.
- `quarry/ui/static/*.css` — `.badge-unknown`, `.badge-work-miss`,
  `.badge-loc-match`, `.badge-loc-miss`.
- `quarry/ui/templates/settings.html` (and settings route) —
  `none_strictness` dropdown in Location Filter section.
- `quarry/agent/scheduler.py` — `skip_reason_counts` Counter + summary log.
- `quarry/store/__main__.py` — add `reset` command.
- `tests/test_pipeline_filter.py` — `evaluate_location_match` truth-table
  tests; `geographic_match` unit tests; update `test_filter_steps_list_exists`.
- `tests/test_ui.py` — read-time filter + badge render tests; settings
  `none_strictness` round-trip test.
- `tests/test_scheduler.py` — ingest-no-longer-filters-location test; ingest
  logging test.
- `tests/test_store_cli.py` — `reset` command tests.
- `docs/STATUS.md` — update after implementation.

## Sequencing

1. **Component 4 (`reset` command)** + tests — unblocks the actual DB reset
   you want to do now; smallest, isolated.
2. **Component 1 (read-time filter)** + truth-table tests — the core change.
   Remove `LocationFilter` from ingest here too; update ingest tests.
3. **Component 2 (badges)** + template/CSS — builds on Component 1's fields.
4. **Component 3 (ingest logging)** — independent, can land anytime after
   Component 1 (so `location` is gone from the summary, demonstrating the
   split).
5. **`none_strictness` Settings UI** — small addition; do alongside
   Component 1 or 2.
6. Run `python -m quarry.store reset --keep-companies`, re-label over the
   fresh crawl, update `docs/STATUS.md`.

## Follow-ups (out of scope)

- GitHub issue #7: TTL to retire stale postings (~60 days).
- Future: fix any remaining `LocationFilter.check` geographic matching bugs
  (e.g. ANY-vs-ALL multi-location semantics) — but only if leaks persist
  after the read-time filter is in place and the corpus is reset.
- Future: classifier feature enrichment (separate title/body embeddings,
  structured location/work features).

## Spec review changelog

### Round 1 (2026-06-19) — test-plan & design-simplicity review (applied)

A fresh-context reviewer flagged 4 blockers and 5 fix-worthy-now gaps; all
load-bearing claims were verified against the code before applying.

Applied fixes:

1. **`LocationFilter.check` reuse double-handling (blocker).** The first
   draft called `LocationFilter.check` via a synthetic `RawPosting`.
   `LocationFilter.check` has early returns (no-filter-configured →
   `passed=True`; empty-`parse_result` → `passed=True`) that contradict
   `evaluate_location_match`'s strict-mode decisions and would render wrong
   badges (unparseable+strict → `✓ location`; remote-only+onsite →
   `✓ location`). Replaced with an extracted `geographic_match(parse_result,
   config)` helper that both `LocationFilter.check` and
   `evaluate_location_match` call; `evaluate_location_match` gates
   (`location_relevant`, `targets_set`, non-remote, non-empty parse_result)
   before calling it, eliminating the double-handling and the synthetic
   shim.
2. **4-boolean model indistinguishability (blocker).** Filter-off and
   remote-only-prefs + None-generous produce identical `work_type_match` /
   `location_relevant` / `location_match` but must render differently. Added
   a `filter_active` flag; the template gates all match/miss assessment
   branches on `filter_active`. Factual `work_model` badges (remote/hybrid/
   onsite) still render when the filter is off.
3. **Template `work: unknown (generous)` on filter-off + None (blocker).**
   Caused by #2; fixed by the `filter_active` gate on the `elif` branch.
4. **`passes` redundant as stored state.** Made it a `@computed_field`
   derived from `filter_active` / `work_type_match` / `location_match` /
   `location_relevant` to prevent drift.
5. **Named the breaking test.** `TestFilterSteps.test_filter_steps_list_exists`
   (`tests/test_pipeline_filter.py:682-689`) asserts `len(FILTER_STEPS)==4`
   with `LocationFilter` at index 3; must be updated to `len==3` without
   `LocationFilter`. Added an explicit grep audit for any other ingest-time
   location tests.
6. **Settings route round-trip data loss.** `settings_location`
   (`quarry/ui/routes.py:465`) constructs `LocationFilterConfig` with an
   explicit field list missing `none_strictness`; saving any location change
   would silently reset strictness to `GENEROUS`. Spec now requires the
   route to read/pass `none_strictness`, and the template dropdown to use
   `.value` for the `selected` comparison.
7. **Added truth-table edge case** `remote` + `accept_remote=false` →
   `passes=False` (in-person-only prefs, posting mislabeled remote), with a
   test case.

Deferred (optional, noted by reviewer, not applied):

- Unify the work-model `elif`/`else` branches into a single computed-label
  branch (current 3-branch form is readable; marginal).
- `location_relevant` becomes derivable if `filter_active` + `targets_set`
  are exposed to the template; kept as stored state for template simplicity.

### Not yet covered

Two planned review angles did **not** complete (subagent dispatch was
SIGTERM-killed by timeout before returning): **plan feasibility/accuracy**
(spec's codebase claims, `reset` table-list completeness, FK dependency
order, `_MODELS_DIR` path) and **correctness/regression risk**
(pagination approximation under post-query Python filtering, SQL/Python
filter composition with interest/title/body filters, multi-user correctness
of the `USER_ID` constant, `reset` FK/CASCADE integrity, config backward
compat for stored JSON without `none_strictness`, `show_all` default-hide UX
after reset). These should be re-run in a fresh session (with the
`pi-review` skill now installed) before implementation begins — they may
surface blockers the applied round did not see.
