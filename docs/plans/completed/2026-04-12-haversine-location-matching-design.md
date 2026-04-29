# Haversine Location Matching

## Problem

The location filter matches jobs only by exact city name, state code, or region. A job in Oakland won't match a filter targeting "San Francisco" because the city names differ, even though they're only ~8 miles apart. The `nearby_radius` config field exists but is unimplemented.

## Solution

Implement haversine-based distance matching in `LocationFilter`. When `nearby_radius` is configured, a job passes the filter if its location is within that radius (in miles) of any resolved target city — in addition to existing exact-match criteria.

## Architecture

### Haversine Utility

Add `haversine_miles(lat1, lon1, lat2, lon2) -> float` to `quarry/pipeline/locations.py`:

- Standard haversine formula using Earth radius = 3958.8 miles
- Returns distance in miles
- Input validation: `None` coordinates return `None` (caller skips distance comparison)
- Pure function, no side effects, easily testable

### Config Changes (`quarry/config.py`)

- `nearby_radius: int | None = None` already exists on `LocationFilterConfig`
- Add `_resolved_target_coords: list[tuple[float, float]]` populated during `normalize_config()`
- Add `_resolved_states_from_accept: set[str]` and `_resolved_regions_from_accept: set[str]` — populated from `accept_states`/`accept_regions`, these always match regardless of whether the posting has a city
- `_resolved_states` and `_resolved_regions` now contain entries from both `target_location` (hierarchical, city-dependent) and `accept_states`/`accept_regions` (non-hierarchical)
- Validation: when `nearby_radius > 0`, require at least one target coordinate. Raise `ValueError` with a clear message if no coordinates resolve
- When `nearby_radius` is `None` or `0`, distance matching is skipped entirely (backward compatible)

### Filter Logic (`quarry/pipeline/filter.py`)

`LocationFilter.check()` uses hierarchical matching — city-level precision when available, state/region as fallbacks only:

```python
for loc in parsed_locations:
    # 1. Exact city match
    if loc.city and loc.city in self._resolved_cities:
        return FilterDecision(passed=True)

    # 2. Haversine distance match (requires coordinates on both sides)
    if self._filter_config.nearby_radius and self._filter_config._resolved_target_coords:
        for target_lat, target_lon in self._filter_config._resolved_target_coords:
            distance = haversine_miles(loc.latitude, loc.longitude, target_lat, target_lon)
            if distance is not None and distance <= self._filter_config.nearby_radius:
                return FilterDecision(passed=True)

    # 3. State fallback — only when posting has no city
    if not loc.city and loc.state_code in self._resolved_states:
        return FilterDecision(passed=True)

    # 4. Region fallback — only when posting has no city and no state
    if not loc.city and not loc.state_code and loc.region in self._resolved_regions:
        return FilterDecision(passed=True)
```

State matching only applies when the posting lacks a city. Region matching only applies when the posting lacks both city and state. This prevents "Fresno, CA" from matching a "San Francisco" target via state — Fresno must match via city name or haversine distance.

### Data Flow

```
config.yaml (target_location: "San Francisco, CA", nearby_radius: 50)
    |
    v
normalize_config() -> resolves via geonamescache -> _resolved_target_coords = [(37.7749, -122.4194)]
    |
    v
LocationFilter.check(posting, parsed_locations)
    |-- Exact match? city/state/region -> PASS
    |-- Distance match? haversine(job_lat, job_lon, target_lat, target_lon) <= 50mi -> PASS
    |-- No match -> FAIL with skip_reason="location"
```

## Edge Cases

| Case | Behavior |
|------|----------|
| `nearby_radius` is `None` or `0` | Distance matching skipped (current behavior preserved) |
| `nearby_radius > 0` but no target coordinates resolve | `ValueError` at config normalization — fail fast |
| ParsedLocation has `latitude=None` or `longitude=None` | `haversine_miles()` returns `None`, skipped — falls through to existing behavior |
| Multiple target cities | Check distance to ALL targets — any within radius passes |
| Remote-only job (`accept_remote=True`) | Still passes via existing remote logic, unaffected |
| Job location resolves to same city as target | Already passes via exact city match, distance check not reached |
| Posting has city + different state from target | Fails — must match by city name or haversine distance, state fallback doesn't apply |
| Posting has state but no city | State matching applies as fallback |
| Posting has region but no city or state | Region matching applies as fallback |

## Testing

1. **Unit: `haversine_miles()`** — known distances:
   - SF → Oakland ≈ 8mi (tolerance ±1mi)
   - SF → LA ≈ 347mi (tolerance ±5mi)
   - Same point → 0mi
   - `None` inputs → `None`

2. **Unit: `LocationFilter` with `nearby_radius`** — nearby city passes, far city fails

3. **Unit: `LocationFilter` without `nearby_radius`** — identical to current behavior (regression test)

4. **Unit: Missing lat/long** — `haversine_miles()` returns `None`, caller skips distance matching

5. **Unit: Config validation** — `nearby_radius > 0` with no resolvable targets raises `ValueError`

## Files Changed

| File | Change |
|------|--------|
| `quarry/pipeline/locations.py` | Add `haversine_miles()` function |
| `quarry/config.py` | Add `_resolved_target_coords` to `LocationFilterConfig`, populate in `normalize_config()`, add validation |
| `quarry/pipeline/filter.py` | Add distance-matching path in `LocationFilter.check()` |
| `tests/test_locations.py` | Tests for `haversine_miles()` |
| `tests/test_filter.py` | Tests for distance-based matching and edge cases |