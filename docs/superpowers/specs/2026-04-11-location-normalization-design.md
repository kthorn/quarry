# Location Normalization Design

## Problem

Job postings have 108 distinct location strings with inconsistent formats:
- Multi-location: `"San Francisco, CA | New York City, NY"` (delimiters: `;`, `|`, `or`)
- Work model prefixes: `"Remote - California"`, `"Hybrid- Fremont, CA"`
- Abbreviation inconsistency: `"CA"` vs `"California"`, `"IE"` vs `"Ireland"`
- City name variants: `"Bangalore"` vs `"Bengaluru"`, `"Zürich"` vs `"Zurich"`
- Vague regions: `"United States"`, `"Central - United States"`, `"USCA"` (these get country-level or region-level location entries with null city)
- The `remote` boolean is unreliable (287 True, 18 False, 292 NULL)

Goal: enable filtering/search by city, state, country, region, and work model.

## Approach

**Approach A (chosen): Junction table + work_model enum + geonamescache normalization**

- New `locations` reference table with structured columns (city, state, country, region, lat/lng)
- New `job_posting_locations` junction table for many-to-many relationships
- New `work_model` enum column on `job_postings` replacing the `remote` boolean
- Use `geonamescache` library for canonical city/state/country resolution
- Custom parsing for compound strings and work model extraction
- DB rebuild (not migration) since it's early stage

## Schema Changes

### New: `locations` table

```sql
CREATE TABLE locations (
    id              INTEGER PRIMARY KEY,
    canonical_name  TEXT NOT NULL UNIQUE,   -- e.g. "San Francisco, CA"
    city            TEXT,                    -- e.g. "San Francisco"
    state           TEXT,                    -- e.g. "California" (or null)
    state_code      TEXT,                    -- e.g. "CA" (or null)
    country         TEXT,                    -- e.g. "United States"
    country_code    TEXT,                    -- e.g. "US"
    region          TEXT,                    -- e.g. "US-West", "Europe"
    latitude        REAL,
    longitude       REAL,
    resolution_status TEXT NOT NULL DEFAULT 'resolved',  -- 'resolved' or 'needs_review'
    raw_fragment    TEXT                    -- original text before normalization (for review)
);
CREATE INDEX idx_locations_canonical ON locations(canonical_name);
CREATE INDEX idx_locations_country ON locations(country_code);
CREATE INDEX idx_locations_region ON locations(region);
```

### New: `job_posting_locations` junction table

```sql
CREATE TABLE job_posting_locations (
    posting_id  INTEGER REFERENCES job_postings(id),
    location_id INTEGER REFERENCES locations(id),
    PRIMARY KEY (posting_id, location_id)
);
CREATE INDEX idx_jpl_posting ON job_posting_locations(posting_id);
CREATE INDEX idx_jpl_location ON job_posting_locations(location_id);
```

### Modified: `job_postings` table

- **Add**: `work_model TEXT` column — values: `'remote'`, `'hybrid'`, `'onsite'`, or `NULL`
- **Drop**: `remote BOOLEAN` column
- **Keep**: `location TEXT` column as the original raw string (for debugging/fallback)

### Migration approach

The existing `init_db()` uses `CREATE TABLE IF NOT EXISTS`, which means it will NOT add `work_model` or drop `remote` on an existing DB. We need an explicit destructive reset.

**Strategy**: Add a `--reset` flag to `python -m quarry.store init` that drops all tables before recreating. Alternatively, add a `quarry.store.migrate` command that:
1. Creates `locations` and `job_posting_locations` tables
2. Adds `work_model TEXT` column to `job_postings`
3. Populates `work_model` from `remote` (True→'remote', False→'onsite', NULL→NULL)
4. Drops `remote` column (SQLite requires table rebuild for DROP COLUMN; simpler to just leave it as unused)

Since we're early stage with ~600 postings, the recommended path is: **delete `quarry.db`, re-run `python -m quarry.store init`, then re-seed and re-crawl**. This is the simplest approach and avoids half-measures.

## Data Transport Shape

The `extract()` function currently returns a single `JobPosting` with a scalar `location` string. After this change, we need a way to carry parsed location data from the pipeline to the DB layer. We'll use a companion dataclass:

```python
@dataclass
class ParsedLocation:
    canonical_name: str          # e.g. "San Francisco, CA"
    city: str | None
    state: str | None
    state_code: str | None
    country: str | None
    country_code: str | None
    region: str | None
    resolution_status: str = "resolved"  # or "needs_review"
    raw_fragment: str | None = None      # original text before normalization
```

The `parse_location()` function returns a `ParseResult`:

```python
@dataclass
class ParseResult:
    work_model: str | None       # 'remote', 'hybrid', 'onsite', or None
    locations: list[ParsedLocation]  # zero or more parsed locations
```

The `extract()` function will call `parse_location()` and return both the `JobPosting` and the `ParseResult`. The caller (either the agent pipeline or the `normalize-locations` CLI command) is responsible for persisting locations via `insert_posting()` + `link_posting_location()`.

This keeps `JobPosting` as a flat Pydantic model (compatible with the DB schema) while carrying structured location data alongside it.

## Parsing Pipeline

New module: `quarry/pipeline/locations.py`

### Step 1: Split compound locations

Split the raw `location` string on these delimiters (in order of precedence):
- ` | ` (pipe with spaces)
- `; ` (semicolon with space)
- ` or ` (the word "or" surrounded by spaces, case-insensitive)

This handles strings like:
- `"San Francisco, CA | New York City, NY"` → `["San Francisco, CA", "New York City, NY"]`
- `"Berlin, Germany; Munich, Germany"` → `["Berlin, Germany", "Munich, Germany"]`
- `"San Francisco, CA, USA or Remote"` → `["San Francisco, CA, USA", "Remote"]`

### Step 2: Extract work model from each fragment

Match and strip these prefixes (case-insensitive):
- `Remote[-\s]?` (e.g., "Remote - California" → work_model=remote, location="California")
- `Hybrid[-\s]?` (e.g., "Hybrid- Fremont, CA" → work_model=hybrid, location="Fremont, CA")
- `Onsite[-\s]?` (e.g., "Onsite- Pittsburgh, PA" → work_model=onsite, location="Pittsburgh, PA")

Special cases:
- `"Remote"` alone → work_model=remote, no location row linked (pure remote, no geo)
- `"Remote - California"` → work_model=remote, location="California" → resolved to California, US

Work model conflict resolution: if multiple fragments have different work model prefixes, take the most specific one preferring: onsite > hybrid > remote. Most commonly all fragments will have the same prefix.

### Step 3: Normalize each location fragment

For each location string after work model extraction:

1. **Whitespace cleanup**: strip, normalize spaces, normalize comma spacing
2. **Alias mapping** (curated dict, first pass before geonamescache):
   - `"IE"` → `"Ireland"`, `"CH"` → `"Switzerland"`, `"USCA"` → flag for manual review
   - `"Bangalore"` → `"Bengaluru"` (geonamescache alternate names may handle this too)
   - `"San Francisco"` (without state) → `"San Francisco, California"` (most common disambiguation)
3. **geonamescache resolution**:
   - Try `search_cities(city_name, case_sensitive=False, contains_search=False)` to find exact name matches
   - For US locations, use `get_us_states()` to resolve state abbreviations (`CA` → `California`)
   - Use `get_countries()` to resolve country codes (`IE` → `Ireland`)
   - When a city matches in multiple countries/states, use the state/country info in the original string to disambiguate
4. **Region assignment**: based on country/state, assign a region tag (see Region Mapping below)
5. **Curated canonical name**: format as `"City, StateCode"` for US, `"City, Country"` for non-US
6. **Country/region-only locations**: entries like "United States" or "Central - United States" get a location row with `city=NULL`, `state=NULL`, `country` and `region` populated, and `canonical_name` set to the country/region name (e.g., "United States")
7. **Fallback**: if geonamescache can't resolve, create a location entry with whatever we can extract, flag for manual review by setting `canonical_name` to the cleaned-up raw string

### Step 4: Dedup and create

- Look up each normalized location in the `locations` table by `canonical_name`
- If exists, link existing row via junction table
- If not, create new row and link

### Step 5: Work model inference

For postings where no work model prefix was found in the location string:
- Run the existing `detect_remote()` heuristics on title + description text to infer work_model (maps: hybrid→`'hybrid'`, remote→`'remote'`, onsite→`'onsite'`, unclear→`NULL`)
- If still unclear, leave `work_model = NULL`

Note: we do NOT create a "Remote" location row for pure-remote postings. Work model is determined by the `work_model` column, not by linking to a location named "Remote".

## Region Mapping

Simple lookup mapping:

```python
US_STATE_REGIONS = {
    # US-West: AK, AZ, CA, CO, HI, ID, MT, NM, NV, OR, UT, WA, WY
    # US-Central: IA, IL, IN, KS, MI, MN, MO, ND, NE, OH, SD, WI
    # US-South: AL, AR, DC, DE, FL, GA, KY, LA, MD, MS, NC, OK, SC, TN, TX, VA, WV
    # US-East: CT, MA, ME, NH, NJ, NY, PA, RI, VT
}

COUNTRY_REGIONS = {
    # Europe: AT, BE, CH, CZ, DE, DK, ES, FI, FR, GB, GR, HR, HU, IE, IT, NL, NO, PL, PT, RO, SE, SK, UA
    # Asia: CN, HK, IN, IL, JP, KR, SG, TW, TH, VN
    # LATAM: AR, BR, CL, CO, MX, PE
    # Oceania: AU, NZ
    # Middle East: AE, BH, EG, IL, QA, SA, TR
    # Africa: ZA, NG, KE, MA
}
```

Based on US Census Bureau regions and standard continental groupings.

## Alias Map

Curated dictionary for cases geonamescache doesn't handle:

```python
LOCATION_ALIASES = {
    # Abbreviated countries
    "IE": "Ireland",
    "CH": "Switzerland",
    "USCA": None,  # flag for manual review

    # Unusual source formats
    "Dublin, IE": "Dublin, Ireland",
    "Zürich, CH": "Zurich, Switzerland",
    "Ontario, CAN": "Ontario, Canada",

    # Common disambiguations without state/country
    "San Francisco": "San Francisco, CA",
    "London": "London, United Kingdom",
    "Paris": "Paris, France",
    "Tokyo": "Tokyo, Japan",
    "Singapore": "Singapore",
}
```

## CLI Command

New command: `python -m quarry.agent.tools normalize-locations`

This will:
1. Query all job_postings with non-null `location`
2. For each posting, run the parsing pipeline
3. Create `locations` rows as needed
4. Create `job_posting_locations` junction rows
5. Set `work_model` on each posting
6. Report stats: X locations created, Y postings processed, Z unresolvable fragments (flagged for review)

## Dependency

Add to `pyproject.toml`:
```
"geonamescache>=3.0.0",
```

~30MB pure Python package, no system dependencies. Provides countries, US states, and cities (min population 15k) with alternate names for fuzzy matching.

**Spike required**: Before implementation, run a quick verification that `geonamescache`'s API covers our actual location corpus. Specifically:
- Confirm `search_cities()` works for our city names (especially Bengaluru, Zürich, etc.)
- Confirm alternate name matching handles our variants (Bangalore→Bengaluru)
- Confirm state code resolution works (CA→California)
- Identify any locations in our corpus that geonamescache can't resolve, so we can add them to the alias map

## Query Examples

```sql
-- All remote jobs
SELECT j.* FROM job_postings j WHERE j.work_model = 'remote';

-- All jobs in San Francisco (including multi-location)
SELECT j.* FROM job_postings j
JOIN job_posting_locations jpl ON j.id = jpl.posting_id
JOIN locations l ON jpl.location_id = l.id
WHERE l.canonical_name = 'San Francisco, CA';

-- All jobs in Europe region
SELECT j.* FROM job_postings j
JOIN job_posting_locations jpl ON j.id = jpl.posting_id
JOIN locations l ON jpl.location_id = l.id
WHERE l.region = 'Europe';

-- All remote or hybrid jobs in US-West
SELECT DISTINCT j.* FROM job_postings j
JOIN job_posting_locations jpl ON j.id = jpl.posting_id
JOIN locations l ON jpl.location_id = l.id
WHERE j.work_model IN ('remote', 'hybrid') AND l.region = 'US-West';
```

## Impact on Existing Code

### `quarry/store/schema.py`
- Add `locations` and `job_posting_locations` table DDL to `SCHEMA_SQL`
- Add `work_model TEXT` column to `job_postings` DDL, remove `remote BOOLEAN`
- Add indexes for location and work_model queries

### `quarry/models.py`
- `JobPosting` (Pydantic `BaseModel`): replace `remote: bool | None` with `work_model: str | None` (values: `'remote'`, `'hybrid'`, `'onsite'`, `None`)
- `RawPosting` (Pydantic `BaseModel`): remove `remote: bool | None = None` field entirely; work model is now determined by the pipeline, not the crawler
- `DigestEntry`: replace `location: str | None = None` — consider adding `work_model: str | None` and a `location_names: list[str]` field

### `quarry/pipeline/extract.py`
- `normalize_location()` → replace with `parse_location()` from `locations.py`; `normalize_location()` can remain as a simple cleanup function used inside the pipeline, but compound parsing and work model extraction moves to the new module
- `detect_remote()` → refactored to return `str | None` (work model: `'remote'`, `'hybrid'`, `'onsite'`, `None`) instead of `bool | None`; currently returns `True` for hybrid, which should become `'hybrid'`
- `extract()`: update to call `parse_location()`, return `(JobPosting, ParseResult)` tuple instead of just `JobPosting`
- Note: this changes the return type of `extract()`, so all callers must be updated

### `quarry/store/db.py`
- `insert_posting()` → update SQL to use `work_model` instead of `remote`; accept `ParseResult` or list of `ParsedLocation` to also insert into `job_posting_locations`
- Add `get_location_by_canonical_name()`, `create_location()`
- Add `link_posting_location()`
- Add query methods: `get_postings_by_location()`, `get_postings_by_region()`, `get_postings_by_work_model()`
- All queries that reference `remote` need updating

### `quarry/agent/crawlers/*.py`
- Greenhouse, Lever, Ashby crawlers → can continue setting raw `location` string; pipeline handles normalization
- Remove `remote` field from `RawPosting` construction in crawlers (Lever, Ashby, JobSpy)
- Lever (`lever.py:53-62`): remove `is_remote = "remote" in location.lower()` and `remote=is_remote`
- Ashby (`ashby.py:82-91`): remove `is_remote = "remote" in location.lower()` and `remote=is_remote`
- JobSpy (`jobspy_client.py`): remove remote detection from `job_type` parsing

### `quarry/pipeline/embedder.py`
- `embed_posting()` → include canonical location name(s) and work_model in embedding text for better clustering
- Need to join through `job_posting_locations` to get location names, or pass `ParseResult` alongside the posting
- Currently `embed_posting()` takes only a `JobPosting` — may need to also take location names or a `ParseResult`

### `quarry/pipeline/filter.py`
- No changes needed; `apply_keyword_blocklist()` already works on text fields

### `quarry/digest/digest.py`
- `build_digest()` → use canonical location name + work_model instead of raw `location` and `remote` fields
- `DigestEntry` model: add `work_model` and consider replacing `location: str | None` with `location_names: list[str]`

### `quarry/agent/scheduler.py`
- Line 36: logs `location` column — update to also log `work_model`
- Line 205: `raw.location or ""` — no change needed (raw location text remains)

### `quarry/pipeline/filter.py`
- No changes needed; `apply_keyword_blocklist()` already works on text fields

### `quarry/digest/digest.py`
- `build_digest()` → use canonical location name + work_model instead of raw `location` and `remote` fields

### Tests (must update)
- `tests/test_extract.py`: references `result.remote` and `result.location` — update to `result.work_model` and check work_model values
- `tests/test_digest.py`: creates postings with `remote=True` and `location=` — update to `work_model='remote'`
- Any tests referencing `JobPosting(remote=...)` need `work_model=` instead
- Add new tests for `quarry/pipeline/locations.py` (splitting, work model extraction, normalization, geonamescache resolution)
- Add tests for `quarry/store/db.py` new location query methods

## Out of Scope

- Geocoding / lat-lng population (columns reserved but not populated in v1)
- UI / labeling interface for location review
- Location-based distance/radius search
- Normalization of ATS-specific location formats at crawl time (still done in pipeline)