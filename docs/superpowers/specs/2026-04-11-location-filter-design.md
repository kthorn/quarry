# Location Filter Design

## Problem

Jobs are discovered from many sources (Greenhouse, Lever, JobSpy, etc.) and the `job_postings` table already captures `location` (normalized text) and `remote` (boolean) fields, but no filtering is applied based on them. Users see jobs from everywhere regardless of whether they're remote or nearby.

## Goal

Add a location filter at ingest time that rejects jobs which are neither remote nor in a set of user-accepted cities, configured via `config.yaml`. The same config should drive JobPy search locations (unified with the current `jobspy_location`).

## Design Decisions

- **Approach:** In-memory substring pattern matching (Approach A). Simple, no external deps, easy to evolve to geocoded radius later.
- **Filter point:** Ingest time, after the similarity threshold check. Rejected jobs are logged to the crawl CSV with `skip_reason="location"` and not inserted into `job_postings`.
- **Backward compatibility:** When `location_filter` is absent from config, all jobs pass (no location filtering).
- **Unknown locations:** If a job's `location` field is empty/None, it passes the filter — we don't reject what we can't identify.
- **JobPy unification:** `nearby_cities` replaces the current single `jobspy_location` string. JobPy fans out across all entries in `nearby_cities`.

## Config Schema

```yaml
location_filter:
  user_location: "San Francisco, CA"    # Primary location label (for display/JobPy default)
  accept_remote: true                    # Remote jobs pass the filter
  accept_nearby: true                    # Enable nearby-city substring matching
  nearby_cities:                         # Substring patterns for location matching
    - "San Francisco"
    - "Oakland"
    - "San Jose"
    - "Palo Alto"
    - "Bay Area"
```

### Config model

Add `LocationFilterConfig` pydantic model to `quarry/config.py`:

```python
class LocationFilterConfig(BaseModel):
    user_location: str
    accept_remote: bool = True
    accept_nearby: bool = True
    nearby_cities: list[str] = []
```

Add `location_filter: LocationFilterConfig | None = None` to `Settings`. When `None`, no location filtering is applied.

Deprecate `jobspy_location` in `Settings` — when `location_filter` is present, `nearby_cities` drives JobPy searches instead.

## Filter Logic

`apply_location_filter(posting, settings) -> tuple[bool, str]` in `quarry/pipeline/filter.py`:

1. If `location_filter` is `None` → pass
2. If `accept_remote` is True and `posting.remote` is True → pass
3. If `posting.location` is empty or None → pass (can't filter unknown)
4. If `accept_nearby` is True and any `nearby_cities` entry appears as a case-insensitive substring in `posting.location` → pass
5. Otherwise → reject with `skip_reason="location"`

Edge case: if both `accept_remote=False` and `accept_nearby=False`, all jobs with a known location are rejected. This is intentionally restrictive — the user has said they don't want remote or nearby jobs.

### Pipeline placement

```
Current:  extract → dedup → keyword_blocklist → similarity → (store)
New:      extract → dedup → keyword_blocklist → location_filter → similarity → (store)
```

The location filter runs BEFORE similarity checking because substring matching is cheap while embedding computation is expensive. Location data (from `posting.location`) comes from `extract()`, which runs before both filters. Running the cheap filter first avoids computing embeddings for jobs that would be rejected by location anyway.

> **Note:** The current keyword_blocklist filter is non-functional (`settings.keyword_blocklist` is never defined). This design doesn't address that but places the location filter in the same layer.

## JobPy Integration

Currently `_crawl_search_queries()` in `quarry/agent/scheduler.py` passes `settings.jobspy_location` (a single string) to JobPy searches.

Change:

- When `location_filter` is configured, generate one JobPy search per entry in `nearby_cities` (and also one using `user_location`).
- Each city's search runs separately; dedup at the URL level already handles overlapping results.
- When `location_filter` is not configured, fall back to the current `jobspy_location` field for backward compatibility.

### Open issue

JobPy may need to run multiple searches when `nearby_cities` has several entries. The current search_queries table and `_crawl_search_queries()` logic should be reviewed to ensure it handles fan-out properly without creating excessive duplicate entries.

## Testing

### Unit tests for `apply_location_filter()`

- No `location_filter` config → all jobs pass
- `accept_remote=True` with remote job → passes
- `accept_remote=False` with remote job → rejected
- `accept_nearby=True` with matching city → passes
- `accept_nearby=True` with non-matching city → rejected
- `accept_nearby=False` → only remote jobs pass (if `accept_remote=True`)
- Empty/None `posting.location` → passes
- Case-insensitive matching
- Substring matching (e.g., "New York" matches "New York, NY")

### Integration test

- End-to-end `_process_posting()` with location filter enabled, verifying rejected jobs get `skip_reason="location"` and are not stored.

### JobPy fan-out test

- Verify that configuring `nearby_cities` generates multiple JobPy search runs (one per city).

## Future Upgrade: Geocoded Radius (Approach C)

The location filter is designed as a strategy that can be swapped:

- v1: `PatternLocationFilter` (substring matching against `nearby_cities`)
- v2: `GeocodedLocationFilter` (geocode `user_location`, geocode each posting, check Haversine distance against `radius_miles`)

Config would extend with:

```yaml
location_filter:
  user_location: "San Francisco, CA"
  accept_remote: true
  accept_nearby: true
  nearby_cities: [...]          # Still drives JobPy searches
  radius_miles: 50              # New: for geocoded filtering
  geocoding_provider: "nominatim"  # New: geocoding service
```

The `nearby_cities` list remains for JobPy integration regardless of which filter strategy is active, since geocoding doesn't help JobPy decide where to search.

The filter interface (`apply_location_filter`) stays the same — only the internal logic changes.