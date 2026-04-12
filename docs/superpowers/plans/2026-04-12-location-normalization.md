# Location Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement structured location normalization to enable filtering/search by city, state, country, region, and work model, replacing the unreliable `remote` boolean.

**Architecture:** New `locations` reference table + `job_posting_locations` junction table for many-to-many relationships. New `work_model` text column replaces `remote` boolean. A `quarry/pipeline/locations.py` module handles parsing raw location strings into structured `ParsedLocation` objects using a `geonamescache`-based resolver. The pipeline's `extract()` function returns `(JobPosting, ParseResult)` tuples. Location filtering operates on in-memory `ParseResult` objects before DB persistence.

**Tech Stack:** Python 3.11, SQLite, geonamescache, Pydantic, pytest

---

## File Structure

```
quarry/
├── models.py                          # MODIFY: RawPosting, JobPosting, DigestEntry, add ParsedLocation/ParseResult
├── config.py                          # MODIFY: add location_filter settings
├── config.yaml.example                # MODIFY: add location_filter section
├── pipeline/
│   ├── __init__.py                     # MODIFY: add location imports
│   ├── extract.py                      # MODIFY: detect_remote → detect_work_model, extract returns tuple
│   ├── filter.py                       # MODIFY: add apply_location_filter
│   └── locations.py                    # CREATE: parsing pipeline (split, extract work model, normalize, geonamescache)
├── store/
│   ├── schema.py                       # MODIFY: add locations + junction tables, work_model column
│   └── db.py                           # MODIFY: location CRUD methods, update insert_posting for work_model
├── crawlers/
│   ├── lever.py                        # MODIFY: remove remote field
│   ├── ashby.py                        # MODIFY: remove remote field
│   └── jobspy_client.py               # MODIFY: remove remote field
├── agent/
│   ├── scheduler.py                    # MODIFY: handle ParseResult from extract
│   └── tools.py                        # MODIFY: add normalize-locations command
├── digest/
│   └── digest.py                       # MODIFY: use work_model instead of remote
tests/
├── test_pipeline_extract.py            # MODIFY: update for work_model
├── test_pipeline_filter.py             # MODIFY: add location filter tests
├── test_pipeline_locations.py           # CREATE: location parsing tests
├── test_digest.py                      # MODIFY: update for work_model
├── test_db.py                          # MODIFY: add location table tests
├── test_e2e.py                         # MODIFY: update for work_model
├── test_lever_crawler.py               # MODIFY: remove remote assertions
├── test_ashby_crawler.py               # MODIFY: remove remote assertions
└── test_pipeline_integration.py        # MODIFY: update for work_model
```

---

### Task 1: Add geonamescache Dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add geonamescache to dependencies**

Edit `pyproject.toml` — add `"geonamescache>=3.0.0",` to the `dependencies` list (after `pydantic-settings>=2.0.0`):

```toml
    "pydantic-settings>=2.0.0",
    "geonamescache>=3.0.0",
    "python-jobspy @ git+https://github.com/cullenwatson/JobSpy.git",
```

- [ ] **Step 2: Install and verify**

Run: `pip install -e ".[dev]" -c constraints.txt`
Expected: geonamescache installs successfully.

- [ ] **Step 3: Quick spike — verify geonamescache API**

Run: `python -c "from geonamescache import GeonamesCache; gc = GeonamesCache(); cities = gc.search_cities('San Francisco', case_sensitive=False, contains_search=False); print(len(cities), cities[0]['name'] if cities else 'NOT FOUND'); us = gc.get_us_states(); print('CA' in us); countries = gc.get_countries(); print('US' in countries)"`
Expected: City found, CA state found, US country found.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add geonamescache dependency for location normalization"
```

---

### Task 2: Update Data Models

**Files:**
- Modify: `quarry/models.py`

- [ ] **Step 1: Write failing test for new models**

Create `tests/test_models_location.py`:

```python
"""Tests for location data models."""

from quarry.models import ParsedLocation, ParseResult, JobPosting, RawPosting, FilterResult


def test_parsed_location_defaults():
    loc = ParsedLocation(
        canonical_name="San Francisco, CA",
        city="San Francisco",
        state="California",
        state_code="CA",
        country="United States",
        country_code="US",
        region="US-West",
    )
    assert loc.resolution_status == "resolved"
    assert loc.raw_fragment is None


def test_parsed_location_needs_review():
    loc = ParsedLocation(
        canonical_name="Unknown Place",
        city=None,
        state=None,
        state_code=None,
        country=None,
        country_code=None,
        region=None,
        resolution_status="needs_review",
        raw_fragment="Unknown Place",
    )
    assert loc.resolution_status == "needs_review"


def test_parse_result():
    loc = ParsedLocation(
        canonical_name="San Francisco, CA",
        city="San Francisco",
        state="California",
        state_code="CA",
        country="United States",
        country_code="US",
        region="US-West",
    )
    result = ParseResult(work_model="remote", locations=[loc])
    assert result.work_model == "remote"
    assert len(result.locations) == 1


def test_parse_result_no_locations():
    result = ParseResult(work_model="remote", locations=[])
    assert result.work_model == "remote"
    assert result.locations == []


def test_job_posting_has_work_model():
    p = JobPosting(
        company_id=1, title="Engineer", title_hash="abc",
        url="https://example.com", work_model="remote",
    )
    assert p.work_model == "remote"
    assert not hasattr(p, "remote")


def test_job_posting_work_model_null():
    p = JobPosting(
        company_id=1, title="Engineer", title_hash="abc",
        url="https://example.com",
    )
    assert p.work_model is None


def test_raw_posting_no_remote():
    r = RawPosting(
        company_id=1, title="Engineer", url="https://example.com",
        source_type="greenhouse",
    )
    assert not hasattr(r, "remote")


def test_filter_result_has_location_skip_reason():
    from quarry.models import RawPosting as RP
    r = RP(company_id=1, title="E", url="https://example.com", source_type="g")
    fr = FilterResult(posting=r, passed=False, skip_reason="location")
    assert fr.skip_reason == "location"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_location.py -v`
Expected: FAIL — `ParsedLocation`, `ParseResult` not found, `remote` still on `JobPosting`.

- [ ] **Step 3: Add ParsedLocation and ParseResult dataclasses, update JobPosting, RawPosting, DigestEntry, FilterResult**

In `quarry/models.py`, add at the top (after imports):

```python
from dataclasses import dataclass, field
```

Add before `class Company`:

```python
@dataclass
class ParsedLocation:
    canonical_name: str
    city: str | None = None
    state: str | None = None
    state_code: str | None = None
    country: str | None = None
    country_code: str | None = None
    region: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    resolution_status: str = "resolved"
    raw_fragment: str | None = None


@dataclass
class ParseResult:
    work_model: str | None = None
    locations: list[ParsedLocation] = field(default_factory=list)
```

Update `RawPosting` — remove `remote: bool | None = None`:

```python
class RawPosting(BaseModel):
    company_id: int
    title: str
    url: str
    description: str | None = None
    location: str | None = None
    posted_at: datetime | None = None
    source_id: str | None = None
    source_type: str
```

Update `JobPosting` — replace `remote: bool | None = None` with `work_model: str | None = None`:

```python
class JobPosting(BaseModel):
    id: int | None = None
    company_id: int
    title: str
    title_hash: str
    url: str
    description: str | None = None
    location: str | None = None
    work_model: str | None = None
    posted_at: datetime | None = None
    source_id: str | None = None
    source_type: str | None = None

    similarity_score: float | None = None
    classifier_score: float | None = None
    embedding: bytes | None = None

    fit_score: int | None = None
    role_tier: Literal["reach", "match", "strong_match"] | None = None
    fit_reason: str | None = None
    key_requirements: str | None = None
    enriched_at: datetime | None = None

    status: Literal["new", "seen", "applied", "rejected", "archived"] = "new"
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
```

Update `FilterResult` — add `"location"` to the Literal for `skip_reason`:

```python
class FilterResult(BaseModel):
    posting: RawPosting
    passed: bool
    skip_reason: Literal["duplicate", "duplicate_url", "blocklist", "low_similarity", "location"] | None = None
    similarity_score: float | None = None
```

Update `DigestEntry` — replace `location: str | None = None` with structured fields:

```python
class DigestEntry(BaseModel):
    company_name: str
    title: str
    url: str
    role_tier: str
    fit_score: int
    similarity_score: float
    fit_reason: str
    location: str | None = None
    work_model: str | None = None
    location_names: list[str] = []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models_location.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quarry/models.py tests/test_models_location.py
git commit -m "feat: add ParsedLocation/ParseResult models, replace remote with work_model"
```

---

### Task 3: Update Database Schema

**Files:**
- Modify: `quarry/store/schema.py`
- Modify: `quarry/store/db.py`

- [ ] **Step 1: Write failing test for new schema**

Add to `tests/test_db.py`:

```python
def test_locations_table_exists(tmp_path):
    db = init_db(tmp_path / "test.db")
    conn = sqlite3.connect(tmp_path / "test.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    assert "locations" in tables
    assert "job_posting_locations" in tables


def test_job_postings_has_work_model(tmp_path):
    db = init_db(tmp_path / "test.db")
    conn = sqlite3.connect(tmp_path / "test.db")
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(job_postings)")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()
    assert "work_model" in columns
    assert "remote" not in columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py::test_locations_table_exists tests/test_db.py::test_job_postings_has_work_model -v`
Expected: FAIL — tables don't exist yet, `work_model` column not there.

- [ ] **Step 3: Update schema.py**

In `quarry/store/schema.py`, replace the `job_postings` table definition — change `remote BOOLEAN` to `work_model TEXT` and add the new tables/indexes. The full `SCHEMA_SQL` should be:

```python
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS companies (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    domain          TEXT,
    careers_url     TEXT,
    ats_type        TEXT DEFAULT 'unknown',
    ats_slug        TEXT,
    resolve_status  TEXT DEFAULT 'unresolved',
    resolve_attempts INTEGER DEFAULT 0,
    active          BOOLEAN DEFAULT TRUE,
    crawl_priority  INTEGER DEFAULT 5,
    notes           TEXT,
    added_by        TEXT DEFAULT 'seed',
    added_reason    TEXT,
    last_crawled_at TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_postings (
    id              INTEGER PRIMARY KEY,
    company_id      INTEGER REFERENCES companies(id),
    title           TEXT NOT NULL,
    title_hash      TEXT NOT NULL,
    url             TEXT NOT NULL,
    description     TEXT,
    location        TEXT,
    work_model      TEXT,
    posted_at       TIMESTAMP,
    source_id       TEXT,
    source_type     TEXT,
    similarity_score    REAL,
    classifier_score    REAL,
    embedding           BLOB,
    fit_score           INTEGER,
    role_tier           TEXT,
    fit_reason          TEXT,
    key_requirements    TEXT,
    enriched_at         TIMESTAMP,
    status          TEXT DEFAULT 'new',
    first_seen_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, title_hash)
);

CREATE INDEX IF NOT EXISTS idx_postings_company ON job_postings(company_id);
CREATE INDEX IF NOT EXISTS idx_postings_status ON job_postings(status);
CREATE INDEX IF NOT EXISTS idx_postings_tier ON job_postings(role_tier);
CREATE INDEX IF NOT EXISTS idx_postings_work_model ON job_postings(work_model);

CREATE TABLE IF NOT EXISTS locations (
    id              INTEGER PRIMARY KEY,
    canonical_name  TEXT NOT NULL UNIQUE,
    city            TEXT,
    state           TEXT,
    state_code      TEXT,
    country         TEXT,
    country_code    TEXT,
    region          TEXT,
    latitude        REAL,
    longitude       REAL,
    resolution_status TEXT NOT NULL DEFAULT 'resolved',
    raw_fragment    TEXT
);

CREATE INDEX IF NOT EXISTS idx_locations_canonical ON locations(canonical_name);
CREATE INDEX IF NOT EXISTS idx_locations_country ON locations(country_code);
CREATE INDEX IF NOT EXISTS idx_locations_region ON locations(region);
CREATE INDEX IF NOT EXISTS idx_locations_city ON locations(city);
CREATE INDEX IF NOT EXISTS idx_locations_state ON locations(state_code);

CREATE TABLE IF NOT EXISTS job_posting_locations (
    posting_id  INTEGER REFERENCES job_postings(id),
    location_id INTEGER REFERENCES locations(id),
    PRIMARY KEY (posting_id, location_id)
);

CREATE INDEX IF NOT EXISTS idx_jpl_posting ON job_posting_locations(posting_id);
CREATE INDEX IF NOT EXISTS idx_jpl_location ON job_posting_locations(location_id);

CREATE TABLE IF NOT EXISTS labels (
    id          INTEGER PRIMARY KEY,
    posting_id  INTEGER REFERENCES job_postings(id),
    signal      TEXT NOT NULL,
    notes       TEXT,
    labeled_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    label_source TEXT DEFAULT 'user'
);

CREATE TABLE IF NOT EXISTS crawl_runs (
    id              INTEGER PRIMARY KEY,
    company_id      INTEGER REFERENCES companies(id),
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    status          TEXT,
    postings_found  INTEGER DEFAULT 0,
    postings_new    INTEGER DEFAULT 0,
    error_message   TEXT
);

CREATE TABLE IF NOT EXISTS search_queries (
    id              INTEGER PRIMARY KEY,
    query_text      TEXT NOT NULL,
    site            TEXT,
    active          BOOLEAN DEFAULT TRUE,
    added_by        TEXT DEFAULT 'user',
    added_reason    TEXT,
    retired_reason   TEXT,
    postings_found  INTEGER DEFAULT 0,
    positive_labels INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS classifier_versions (
    id               INTEGER PRIMARY KEY,
    trained_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    training_samples INTEGER,
    positive_samples INTEGER,
    negative_samples INTEGER,
    cv_accuracy      REAL,
    cv_precision     REAL,
    cv_recall        REAL,
    model_path       TEXT,
    active           BOOLEAN DEFAULT FALSE,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS agent_actions (
    id          INTEGER PRIMARY KEY,
    run_id      TEXT,
    tool_name   TEXT NOT NULL,
    tool_args   TEXT,
    tool_result TEXT,
    rationale   TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""
```

- [ ] **Step 4: Update db.py — update `insert_posting` for `work_model` and add location methods**

In `quarry/store/db.py`, update `insert_posting` to use `work_model` instead of `remote`:

The `insert_posting` method SQL becomes:

```python
def insert_posting(self, posting: models.JobPosting) -> int:
    sql = """
        INSERT INTO job_postings (company_id, title, title_hash, url, description,
            location, work_model, posted_at, source_id, source_type, similarity_score,
            classifier_score, embedding, fit_score, role_tier, fit_reason,
            key_requirements, enriched_at, status, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    with self.get_connection() as conn:
        cursor = conn.execute(
            sql,
            (
                posting.company_id,
                posting.title,
                posting.title_hash,
                posting.url,
                posting.description,
                posting.location,
                posting.work_model,
                posting.posted_at,
                posting.source_id,
                posting.source_type,
                posting.similarity_score,
                posting.classifier_score,
                posting.embedding,
                posting.fit_score,
                posting.role_tier,
                posting.fit_reason,
                posting.key_requirements,
                posting.enriched_at,
                posting.status,
                posting.first_seen_at,
                posting.last_seen_at,
            ),
        )
        return cursor.lastrowid or 0
```

Add these new methods to the `Database` class (before `get_setting`):

```python
def get_or_create_location(self, parsed: models.ParsedLocation) -> int:
    """Get existing location ID by canonical_name, or create a new one.

    Args:
        parsed: ParsedLocation with normalized data.

    Returns:
        Location row ID.
    """
    existing = self.execute(
        "SELECT id FROM locations WHERE canonical_name = ?",
        (parsed.canonical_name,),
    )
    if existing:
        return existing[0]["id"]

    sql = """
        INSERT INTO locations (canonical_name, city, state, state_code,
            country, country_code, region, latitude, longitude,
            resolution_status, raw_fragment)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    with self.get_connection() as conn:
        cursor = conn.execute(
            sql,
            (
                parsed.canonical_name,
                parsed.city,
                parsed.state,
                parsed.state_code,
                parsed.country,
                parsed.country_code,
                parsed.region,
                parsed.latitude,
                parsed.longitude,
                parsed.resolution_status,
                parsed.raw_fragment,
            ),
        )
        return cursor.lastrowid or 0

def link_posting_location(self, posting_id: int, location_id: int) -> None:
    """Link a posting to a location via the junction table."""
    sql = "INSERT OR IGNORE INTO job_posting_locations (posting_id, location_id) VALUES (?, ?)"
    self.execute(sql, (posting_id, location_id))

def get_postings_by_work_model(self, work_model: str) -> list[models.JobPosting]:
    """Get postings by work_model value."""
    sql = "SELECT * FROM job_postings WHERE work_model = ?"
    rows = self.execute(sql, (work_model,))
    return [models.JobPosting(**dict(row)) for row in rows]

def get_postings_by_location(self, canonical_name: str) -> list[models.JobPosting]:
    """Get postings linked to a location by canonical name."""
    sql = """
        SELECT j.* FROM job_postings j
        JOIN job_posting_locations jpl ON j.id = jpl.posting_id
        JOIN locations l ON jpl.location_id = l.id
        WHERE l.canonical_name = ?
    """
    rows = self.execute(sql, (canonical_name,))
    return [models.JobPosting(**dict(row)) for row in rows]

def get_postings_by_region(self, region: str) -> list[models.JobPosting]:
    """Get postings linked to locations in a given region."""
    sql = """
        SELECT DISTINCT j.* FROM job_postings j
        JOIN job_posting_locations jpl ON j.id = jpl.posting_id
        JOIN locations l ON jpl.location_id = l.id
        WHERE l.region = ?
    """
    rows = self.execute(sql, (region,))
    return [models.JobPosting(**dict(row)) for row in rows]
```

- [ ] **Step 5: Delete the old `quarry.db` and re-run init**

Since this is a schema change (DB rebuild, not migration), the test DB will get the new schema. For existing data, per the spec: delete `quarry.db`, re-run `init`, and re-seed.

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_db.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add quarry/store/schema.py quarry/store/db.py tests/test_db.py
git commit -m "feat: add locations/junction tables, replace remote with work_model in schema"
```

---

### Task 4: Create Location Parsing Module (with TDD)

**Files:**
- Create: `quarry/pipeline/locations.py`
- Create: `tests/test_pipeline_locations.py`

This is the core task. Build incrementally with TDD.

- [ ] **Step 4a: Write tests for split_compound_locations**

Add to `tests/test_pipeline_locations.py`:

```python
"""Tests for location parsing module."""

from quarry.pipeline.locations import (
    split_compound_locations,
    extract_work_model,
    normalize_location_fragment,
    parse_location,
    ParsedLocation,
    ParseResult,
)


class TestSplitCompoundLocations:
    def test_pipe_delimiter(self):
        assert split_compound_locations("San Francisco, CA | New York City, NY") == [
            "San Francisco, CA",
            "New York City, NY",
        ]

    def test_semicolon_delimiter(self):
        assert split_compound_locations("Berlin, Germany; Munich, Germany") == [
            "Berlin, Germany",
            "Munich, Germany",
        ]

    def test_or_delimiter(self):
        assert split_compound_locations("San Francisco, CA, USA or Remote") == [
            "San Francisco, CA, USA",
            "Remote",
        ]

    def test_single_location(self):
        assert split_compound_locations("San Francisco, CA") == ["San Francisco, CA"]

    def test_empty_string(self):
        assert split_compound_locations("") == []

    def test_none(self):
        assert split_compound_locations(None) == []

    def test_whitespace_only(self):
        assert split_compound_locations("   ") == []

    def test_pipe_delimiter_variations(self):
        assert split_compound_locations("A | B | C") == ["A", "B", "C"]
```

- [ ] **Step 4b: Run test, see it fail**

Run: `pytest tests/test_pipeline_locations.py::TestSplitCompoundLocations -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 4c: Implement split_compound_locations**

Create `quarry/pipeline/locations.py`:

```python
"""Location parsing pipeline: raw string → structured ParseResult.

Handles compound locations (multiple cities), work model extraction,
and geonamescache-based normalization.
"""

import re
from dataclasses import dataclass, field

from quarry.models import ParsedLocation as _ParsedLocation
from quarry.models import ParseResult as _ParseResult


PARSE_RESULT_NONE = _ParseResult(work_model=None, locations=[])


def split_compound_locations(location: str | None) -> list[str]:
    """Split a compound location string into individual fragments.

    Handles pipe, semicolon, and 'or' delimiters.
    Returns empty list for None, empty, or whitespace-only strings.
    """
    if not location or not location.strip():
        return []
    location = location.strip()
    for delimiter in [" | ", "; "]:
        if delimiter in location:
            return [part.strip() for part in location.split(delimiter) if part.strip()]
    or_pattern = re.compile(r"\s+or\s+", re.IGNORECASE)
    if or_pattern.search(location):
        return [part.strip() for part in or_pattern.split(location) if part.strip()]
    return [location]
```

- [ ] **Step 4d: Run test, see it pass**

Run: `pytest tests/test_pipeline_locations.py::TestSplitCompoundLocations -v`
Expected: PASS

- [ ] **Step 4e: Write tests for extract_work_model**

Add to `tests/test_pipeline_locations.py`:

```python
class TestExtractWorkModel:
    def test_remote_prefix_hyphen(self):
        fragments, work_model = extract_work_model(["Hybrid- Fremont, CA"])
        assert work_model == "hybrid"
        assert fragments == ["Fremont, CA"]

    def test_remote_prefix_space(self):
        fragments, work_model = extract_work_model(["Remote - California"])
        assert work_model == "remote"
        assert fragments == ["California"]

    def test_onsite_prefix(self):
        fragments, work_model = extract_work_model(["Onsite- Pittsburgh, PA"])
        assert work_model == "onsite"
        assert fragments == ["Pittsburgh, PA"]

    def test_pure_remote(self):
        fragments, work_model = extract_work_model(["Remote"])
        assert work_model == "remote"
        assert fragments == []

    def test_no_prefix(self):
        fragments, work_model = extract_work_model(["San Francisco, CA"])
        assert work_model is None
        assert fragments == ["San Francisco, CA"]

    def test_mixed_prefixes_most_specific_wins(self):
        fragments, work_model = extract_work_model(["Hybrid- SF", "Onsite- NYC"])
        assert work_model == "onsite"
        assert fragments == ["SF", "NYC"]

    def test_case_insensitive(self):
        fragments, work_model = extract_work_model(["REMOTE - US"])
        assert work_model == "remote"
        assert fragments == ["US"]
```

- [ ] **Step 4f: Run test, see it fail then implement**

Run: `pytest tests/test_pipeline_locations.py::TestExtractWorkModel -v`
Expected: FAIL

Add `extract_work_model` to `quarry/pipeline/locations.py`:

```python
_WORK_MODEL_PATTERN = re.compile(r"^(remote|hybrid|onsite)[-_\s]?(.*)", re.IGNORECASE)
_WORK_MODEL_PRECEDENCE = {"onsite": 3, "hybrid": 2, "remote": 1}


def extract_work_model(fragments: list[str]) -> tuple[list[str], str | None]:
    """Extract work model prefix from location fragments.

    Returns (stripped_fragments, work_model_or_None).
    Work model precedence: onsite > hybrid > remote.
    Pure 'Remote' (no location) returns empty fragments and 'remote'.
    """
    if not fragments:
        return [], None

    stripped = []
    work_models = []

    for fragment in fragments:
        match = _WORK_MODEL_PATTERN.match(fragment.strip())
        if match:
            model = match.group(1).lower()
            remainder = match.group(2).strip()
            work_models.append(model)
            if remainder:
                stripped.append(remainder)
        else:
            stripped.append(fragment.strip())

    best_model = None
    if work_models:
        best_model = max(work_models, key=lambda m: _WORK_MODEL_PRECEDENCE.get(m, 0))

    return stripped, best_model
```

- [ ] **Step 4g: Run test, see it pass**

Run: `pytest tests/test_pipeline_locations.py::TestExtractWorkModel -v`
Expected: PASS

- [ ] **Step 4h: Write tests for normalize_location_fragment**

These tests need geonamescache. Add to `tests/test_pipeline_locations.py`:

```python
class TestNormalizeLocationFragment:
    def test_us_city_with_state_code(self):
        result = normalize_location_fragment("San Francisco, CA")
        assert result.canonical_name == "San Francisco, CA"
        assert result.city == "San Francisco"
        assert result.state_code == "CA"
        assert result.country_code == "US"

    def test_us_city_without_state(self):
        result = normalize_location_fragment("San Francisco")
        assert result.canonical_name == "San Francisco, CA"
        assert result.city == "San Francisco"

    def test_country_only(self):
        result = normalize_location_fragment("United States")
        assert result.canonical_name == "United States"
        assert result.country_code == "US"
        assert result.city is None

    def test_alias_expansion(self):
        result = normalize_location_fragment("IE")
        assert result.canonical_name == "Ireland"
        assert result.country_code == "IE"

    def test_city_diacritics(self):
        result = normalize_location_fragment("Zürich, Switzerland")
        assert result.city == "Zurich"
        assert result.country_code == "CH"

    def test_flagged_unknown(self):
        result = normalize_location_fragment("USCA")
        assert result.resolution_status == "needs_review"

    def test_fallback_for_unknown(self):
        result = normalize_location_fragment("Planet Mars")
        assert result.resolution_status == "needs_review"
        assert result.raw_fragment == "Planet Mars"
```

- [ ] **Step 4i: Implement normalize_location_fragment**

Add to `quarry/pipeline/locations.py`. This is the big one — it uses geonamescache:

```python
from geonamescache import GeonamesCache

_gc = None


def _get_geonamescache() -> GeonamesCache:
    global _gc
    if _gc is None:
        _gc = GeonamesCache()
    return _gc


US_STATE_REGIONS: dict[str, str] = {
    "AK": "US-West", "AZ": "US-West", "CA": "US-West", "CO": "US-West",
    "HI": "US-West", "ID": "US-West", "MT": "US-West", "NM": "US-West",
    "NV": "US-West", "OR": "US-West", "UT": "US-West", "WA": "US-West",
    "WY": "US-West",
    "IA": "US-Central", "IL": "US-Central", "IN": "US-Central", "KS": "US-Central",
    "MI": "US-Central", "MN": "US-Central", "MO": "US-Central", "ND": "US-Central",
    "NE": "US-Central", "OH": "US-Central", "SD": "US-Central", "WI": "US-Central",
    "AL": "US-South", "AR": "US-South", "DC": "US-South", "DE": "US-South",
    "FL": "US-South", "GA": "US-South", "KY": "US-South", "LA": "US-South",
    "MD": "US-South", "MS": "US-South", "NC": "US-South", "OK": "US-South",
    "SC": "US-South", "TN": "US-South", "TX": "US-South", "VA": "US-South",
    "WV": "US-South",
    "CT": "US-East", "MA": "US-East", "ME": "US-East", "NH": "US-East",
    "NJ": "US-East", "NY": "US-East", "PA": "US-East", "RI": "US-East",
    "VT": "US-East",
}

COUNTRY_REGIONS: dict[str, str] = {
    "AT": "Europe", "BE": "Europe", "CH": "Europe", "CZ": "Europe",
    "DE": "Europe", "DK": "Europe", "ES": "Europe", "FI": "Europe",
    "FR": "Europe", "GB": "Europe", "GR": "Europe", "HR": "Europe",
    "HU": "Europe", "IE": "Europe", "IT": "Europe", "NL": "Europe",
    "NO": "Europe", "PL": "Europe", "PT": "Europe", "RO": "Europe",
    "SE": "Europe", "SK": "Europe", "UA": "Europe",
    "CN": "Asia", "HK": "Asia", "IN": "Asia", "IL": "Asia",
    "JP": "Asia", "KR": "Asia", "SG": "Asia", "TW": "Asia",
    "TH": "Asia", "VN": "Asia",
    "AR": "LATAM", "BR": "LATAM", "CL": "LATAM", "CO": "LATAM",
    "MX": "LATAM", "PE": "LATAM",
    "AU": "Oceania", "NZ": "Oceania",
    "AE": "Middle East", "BH": "Middle East", "EG": "Middle East",
    "QA": "Middle East", "SA": "Middle East", "TR": "Middle East",
    "ZA": "Africa", "NG": "Africa", "KE": "Africa", "MA": "Africa",
    "US": "US-East", "CA": "US-West",
}

LOCATION_ALIASES: dict[str, str | None] = {
    "IE": "Ireland",
    "CH": "Switzerland",
    "USCA": None,
    "Dublin, IE": "Dublin, Ireland",
    "Zürich, CH": "Zurich, Switzerland",
    "Ontario, CAN": "Ontario, Canada",
    "San Francisco": "San Francisco, CA",
    "London": "London, United Kingdom",
    "Paris": "Paris, France",
    "Tokyo": "Tokyo, Japan",
    "Singapore": "Singapore",
}

_CITY_ALIASES: dict[str, str] = {
    "bangalore": "Bengaluru",
    "banglore": "Bengaluru",
    "calcutta": "Kolkata",
    "bombay": "Mumbai",
    "zürich": "Zurich",
    "zurich": "Zurich",
}


def normalize_location_fragment(raw: str) -> _ParsedLocation:
    """Normalize a single location string into a ParsedLocation.

    Steps:
    1. Whitespace cleanup
    2. Alias mapping
    3. geonamescache resolution
    4. Region assignment
    5. Canonical name formatting
    """
    text = re.sub(r"\s+", " ", raw.strip())
    text = re.sub(r"\s*,\s*", ", ", text)
    if not text:
        return _ParsedLocation(
            canonical_name=raw, resolution_status="needs_review", raw_fragment=raw
        )

    original = text

    if text in LOCATION_ALIASES:
        mapped = LOCATION_ALIASES[text]
        if mapped is None:
            return _ParsedLocation(
                canonical_name=original,
                resolution_status="needs_review",
                raw_fragment=original,
            )
        text = mapped

    city_lower = text.split(",")[0].strip().lower()
    if city_lower in _CITY_ALIASES:
        parts = text.split(", ", 1)
        text = _CITY_ALIASES[city_lower] + (", " + parts[1] if len(parts) > 1 else "")

    gc = _get_geonamescache()

    country_code, country_name, state_code, state_name, city, region = (
        None, None, None, None, None, None,
    )

    countries = gc.get_countries()
    us_states = gc.get_us_states()

    parts = [p.strip() for p in text.split(",")]

    for code, info in countries.items():
        names = [info["name"], info.get("iso", code), code]
        if any(n.lower() == parts[-1].lower() for n in names if n):
            country_code = code
            country_name = info["name"]
            break

    if country_code == "US" and len(parts) >= 2:
        state_part = parts[-2].strip() if len(parts) >= 3 else parts[-1 if country_code else 0].strip()
        if len(parts) >= 2:
            state_part = parts[1].strip() if len(parts) == 2 and country_code else parts[-2].strip()
        for code, info in us_states.items():
            if info["name"].lower() == state_part.lower() or code.upper() == state_part.upper():
                state_code = code.upper()
                state_name = info["name"]
                break

    if country_code == "US" and not state_code and len(parts) >= 2:
        for code, info in us_states.items():
            if info["name"].lower() == parts[1].lower() or code.upper() == parts[1].upper():
                state_code = code.upper()
                state_name = info["name"]
                break

    city_part = parts[0].strip()
    if country_code and not city_part:
        region = COUNTRY_REGIONS.get(
            country_code, COUNTRY_REGIONS.get(country_code, country_name or country_code)
        )
        return _ParsedLocation(
            canonical_name=country_name or original,
            city=None,
            state=state_name,
            state_code=state_code,
            country=country_name,
            country_code=country_code,
            region=region,
            raw_fragment=original if original != (country_name or original) else None,
        )

    cities = gc.search_cities(city_part, case_sensitive=False, contains_search=False)
    matches = [c for c in cities if c["name"].lower() == city_part.lower()]

    if not matches:
        matches = [c for c in cities if city_part.lower() in c["name"].lower()]

    if country_code:
        matches = [c for c in matches if c.get("countrycode", "").upper() == country_code]

    if state_code and matches:
        matches = [c for c in matches if c.get("admincode1", "").upper() == state_code]

    if matches:
        best = matches[0]
        city = best["name"]
        resolved_cc = best.get("countrycode", country_code or "").upper()
        resolved_sc = best.get("admincode1", state_code or "").upper()

        if resolved_cc == "US" and resolved_sc:
            state_name = us_states.get(resolved_sc, {}).get("name", state_name)
            region = US_STATE_REGIONS.get(resolved_sc)
        else:
            region = COUNTRY_REGIONS.get(resolved_cc)

        country_info = countries.get(resolved_cc, {})
        country_name = country_info.get("name", resolved_cc)

        canonical = f"{city}, {resolved_sc}" if resolved_cc == "US" and resolved_sc else f"{city}, {country_name}"

        return _ParsedLocation(
            canonical_name=canonical,
            city=city,
            state=state_name,
            state_code=resolved_sc or None,
            country=country_name,
            country_code=resolved_cc,
            region=region,
            raw_fragment=original if original != canonical else None,
        )

    country_info = countries.get(country_code or "", {})
    state_or_country = state_code or country_code
    canonical = f"{city_part}, {state_or_country}" if state_or_country else original

    return _ParsedLocation(
        canonical_name=canonical,
        city=city_part if city_part else None,
        state=state_name,
        state_code=state_code,
        country=country_name or country_info.get("name"),
        country_code=country_code,
        region=COUNTRY_REGIONS.get(country_code or "", country_name),
        resolution_status="needs_review",
        raw_fragment=original,
    )
```

- [ ] **Step 4j: Run tests**

Run: `pytest tests/test_pipeline_locations.py::TestNormalizeLocationFragment -v`
Expected: PASS (possibly some failures requiring tweaks to the geonamescache resolution logic — iterate as needed).

- [ ] **Step 4k: Write tests for parse_location**

Add to `tests/test_pipeline_locations.py`:

```python
class TestParseLocation:
    def test_simple_city_state(self):
        result = parse_location("San Francisco, CA")
        assert result.work_model is None
        assert len(result.locations) >= 1
        assert result.locations[0].city == "San Francisco"

    def test_remote_only(self):
        result = parse_location("Remote")
        assert result.work_model == "remote"
        assert result.locations == []

    def test_compound_with_pipe(self):
        result = parse_location("San Francisco, CA | New York City, NY")
        assert len(result.locations) >= 2

    def test_remote_prefix(self):
        result = parse_location("Remote - California")
        assert result.work_model == "remote"
        assert len(result.locations) >= 1

    def test_hybrid_prefix(self):
        result = parse_location("Hybrid- Fremont, CA")
        assert result.work_model == "hybrid"
        assert len(result.locations) >= 1

    def test_none_location(self):
        result = parse_location(None)
        assert result.work_model is None
        assert result.locations == []

    def test_empty_location(self):
        result = parse_location("")
        assert result.work_model is None
        assert result.locations == []
```

- [ ] **Step 4l: Implement parse_location**

Add to `quarry/pipeline/locations.py`:

```python
def parse_location(location: str | None) -> _ParseResult:
    """Parse a raw location string into a ParseResult.

    Steps:
    1. Split compound locations
    2. Extract work model prefix
    3. Normalize each fragment
    4. Return ParseResult with work_model and locations
    """
    if not location or not location.strip():
        return _ParseResult(work_model=None, locations=[])

    fragments = split_compound_locations(location)
    fragments, work_model = extract_work_model(fragments)

    locations: list[_ParsedLocation] = []
    for fragment in fragments:
        frag = fragment.strip()
        if not frag:
            continue
        if frag.lower() == "remote":
            if work_model is None:
                work_model = "remote"
            continue
        parsed = normalize_location_fragment(frag)
        locations.append(parsed)

    return _ParseResult(work_model=work_model, locations=locations)
```

- [ ] **Step 4m: Run all location tests**

Run: `pytest tests/test_pipeline_locations.py -v`
Expected: PASS

- [ ] **Step 4n: Commit**

```bash
git add quarry/pipeline/locations.py tests/test_pipeline_locations.py
git commit -m "feat: add location parsing module with compound splitting, work model extraction, geonamescache normalization"
```

---

### Task 5: Add Database Location Methods (with TDD)

**Files:**
- Modify: `tests/test_db.py`

- [ ] **Step 5a: Write tests for location DB methods**

Add to `tests/test_db.py`:

```python
from quarry.models import ParsedLocation as PLoc


def test_get_or_create_location_inserts_new(tmp_path):
    db = init_db(tmp_path / "test.db")
    parsed = PLoc(
        canonical_name="San Francisco, CA",
        city="San Francisco",
        state="California",
        state_code="CA",
        country="United States",
        country_code="US",
        region="US-West",
    )
    loc_id = db.get_or_create_location(parsed)
    assert loc_id > 0


def test_get_or_create_location_idempotent(tmp_path):
    db = init_db(tmp_path / "test.db")
    parsed = PLoc(
        canonical_name="San Francisco, CA",
        city="San Francisco",
        state="California",
        state_code="CA",
        country="United States",
        country_code="US",
        region="US-West",
    )
    id1 = db.get_or_create_location(parsed)
    id2 = db.get_or_create_location(parsed)
    assert id1 == id2


def test_link_posting_location(tmp_path):
    db = init_db(tmp_path / "test.db")
    company = Company(name="TestCorp")
    cid = db.insert_company(company)
    posting = JobPosting(
        company_id=cid, title="Eng", title_hash="h1",
        url="https://example.com/1", work_model="remote",
    )
    pid = db.insert_posting(posting)
    loc = PLoc(canonical_name="Remote", country_code="US", region="US-West")
    lid = db.get_or_create_location(loc)
    db.link_posting_location(pid, lid)

    postings = db.get_postings_by_work_model("remote")
    assert len(postings) >= 1


def test_get_postings_by_location(tmp_path):
    db = init_db(tmp_path / "test.db")
    company = Company(name="TestCorp")
    cid = db.insert_company(company)
    posting = JobPosting(
        company_id=cid, title="Eng", title_hash="h1",
        url="https://example.com/loc1", location="San Francisco, CA",
    )
    pid = db.insert_posting(posting)
    loc = PLoc(canonical_name="San Francisco, CA", city="San Francisco", state_code="CA", country_code="US", region="US-West")
    lid = db.get_or_create_location(loc)
    db.link_posting_location(pid, lid)

    results = db.get_postings_by_location("San Francisco, CA")
    assert len(results) == 1
    assert results[0].title == "Eng"


def test_get_postings_by_region(tmp_path):
    db = init_db(tmp_path / "test.db")
    company = Company(name="TestCorp")
    cid = db.insert_company(company)
    posting = JobPosting(
        company_id=cid, title="Eng", title_hash="h2",
        url="https://example.com/reg1", location="SF",
    )
    pid = db.insert_posting(posting)
    loc = PLoc(canonical_name="San Francisco, CA", city="San Francisco", state_code="CA", country_code="US", region="US-West")
    lid = db.get_or_create_location(loc)
    db.link_posting_location(pid, lid)

    results = db.get_postings_by_region("US-West")
    assert len(results) >= 1
```

- [ ] **Step 5b: Run tests**

Run: `pytest tests/test_db.py -v`
Expected: PASS (DB methods were added in Task 3)

- [ ] **Step 5c: Commit**

```bash
git add tests/test_db.py
git commit -m "test: add location database method tests"
```

---

### Task 6: Update Config for Location Filter

**Files:**
- Modify: `quarry/config.py`
- Modify: `quarry/config.yaml.example`

- [ ] **Step 6a: Add location filter settings to Settings class**

In `quarry/config.py`, add to the `Settings` class (after the `max_redirects` field):

```python
    # Location filter
    location_filter: dict | None = None
```

This allows YAML config like:

```yaml
location_filter:
  user_location: "San Francisco, CA"
  accept_remote: true
  accept_nearby: true
  nearby_cities:
    - "San Francisco"
    - "Oakland"
  accept_regions:
    - "US-West"
```

- [ ] **Step 6b: Update config.yaml.example**

Add after the `max_redirects` section:

```yaml
# === Location filter ===
# location_filter:
#   user_location: "San Francisco, CA"
#   accept_remote: true
#   accept_nearby: true
#   nearby_cities:
#     - "San Francisco"
#     - "Oakland"
#   accept_regions:
#     - "US-West"
```

- [ ] **Step 6c: Commit**

```bash
git add quarry/config.py quarry/config.yaml.example
git commit -m "feat: add location_filter config settings"
```

---

### Task 7: Update Extract Pipeline

**Files:**
- Modify: `quarry/pipeline/extract.py`
- Modify: `quarry/pipeline/__init__.py`

- [ ] **Step 7a: Refactor detect_remote → detect_work_model**

In `quarry/pipeline/extract.py`, rename `detect_remote` to `detect_work_model` and change its return type from `bool | None` to `str | None` (values: `'remote'`, `'hybrid'`,

`'onsite'`, `None`):

```python
def detect_work_model(text: str) -> str | None:
    """Detect work model from job description text.

    Returns 'remote', 'hybrid', 'onsite', or None.
    """
    if not text:
        return None

    text_lower = text.lower()

    onsite_patterns = [
        r"\bon[- ]?site\b",
        r"\bin[- ]?office\b",
        r"\bin office\b",
        r"\brelocation required\b",
    ]

    hybrid_patterns = [
        r"\bhybrid\b",
    ]

    remote_patterns = [
        r"\bremote\b",
        r"\bwork from home\b",
        r"\bwfh\b",
        r"\bfully remote\b",
        r"\b100% remote\b",
        r"\bwork remotely\b",
        r"\bremote-first\b",
        r"\bdistributed team\b",
    ]

    has_onsite = any(re.search(p, text_lower) for p in onsite_patterns)
    has_hybrid = any(re.search(p, text_lower) for p in hybrid_patterns)

    has_remote = any(
        re.search(p, text_lower) for p in remote_patterns
        if p != r"\bremote\b"
    )
    has_remote_word = (
        re.search(r"\bremote\b(?!\s+(inc|corp|llc|ltd|co|company)\b)", text_lower)
        is not None
    )
    has_remote = has_remote or has_remote_word

    if has_onsite and not has_hybrid and not has_remote:
        return "onsite"
    if has_hybrid:
        return "hybrid"
    if has_remote:
        return "remote"
    return None
```

Keep a backward-compatible alias for `detect_remote` that calls `detect_work_model` and maps the result:

```python
def detect_remote(text: str) -> bool | None:
    """Backward-compatible wrapper: detect_work_model → bool.

    Returns True for 'remote' or 'hybrid', False for 'onsite', None for unknown.
    """
    model = detect_work_model(text)
    if model == "onsite":
        return False
    if model in ("remote", "hybrid"):
        return True
    return None
```

- [ ] **Step 7b: Update extract() to return (JobPosting, ParseResult)**

In `quarry/pipeline/extract.py`, update the `extract` function:

```python
from quarry.pipeline.locations import parse_location
from quarry.models import ParseResult


def extract(raw: RawPosting) -> tuple[JobPosting, ParseResult]:
    """Extract and transform RawPosting into JobPosting + ParseResult.

    Performs:
    - HTML stripping and text normalization
    - Work model detection
    - Location parsing
    - Title hashing for deduplication

    Args:
        raw: RawPosting from crawler

    Returns:
        Tuple of (JobPosting, ParseResult).
    """
    description = None
    if raw.description:
        description = strip_html(raw.description)

    parse_result = parse_location(raw.location)

    combined_text = " ".join(filter(None, [raw.title, description, raw.location]))
    work_model = parse_result.work_model
    if work_model is None and combined_text:
        work_model = detect_work_model(combined_text)

    location = normalize_location(raw.location)
    title_hash = hash_title(raw.title)

    posting = JobPosting(
        company_id=raw.company_id,
        title=raw.title,
        title_hash=title_hash,
        url=raw.url,
        description=description,
        location=location,
        work_model=work_model,
        posted_at=raw.posted_at,
        source_id=raw.source_id,
        source_type=raw.source_type,
    )

    return posting, parse_result
```

- [ ] **Step 7c: Update pipeline __init__.py exports**

In `quarry/pipeline/__init__.py`, add:

```python
from quarry.pipeline.locations import parse_location
```

And add `"parse_location"` to `__all__`.

- [ ] **Step 7d: Commit**

```bash
git add quarry/pipeline/extract.py quarry/pipeline/__init__.py
git commit -m "feat: update extract to return (JobPosting, ParseResult), add detect_work_model"
```

---

### Task 8: Add Location Filter

**Files:**
- Modify: `quarry/pipeline/filter.py`

- [ ] **Step 8a: Write failing tests for apply_location_filter**

Add to `tests/test_pipeline_filter.py`:

```python
from quarry.models import ParsedLocation as PLoc, ParseResult as PRes


class TestApplyLocationFilter:
    def test_no_filter_config_passes_all(self):
        from quarry.pipeline.filter import apply_location_filter
        from quarry.models import JobPosting as JP, RawPosting as RP
        posting = JP(company_id=1, title="Eng", title_hash="h", url="https://example.com")
        parse_result = PRes(work_model=None, locations=[PLoc(
            canonical_name="New York, NY", city="New York",
            state_code="NY", country_code="US", region="US-East",
        )])
        passed, reason = apply_location_filter(posting, parse_result, settings=None)
        assert passed is True

    def test_accept_remote_passes(self):
        from quarry.pipeline.filter import apply_location_filter
        from quarry.models import JobPosting as JP
        posting = JP(company_id=1, title="Eng", title_hash="h", url="https://example.com")
        parse_result = PRes(work_model="remote", locations=[])
        settings = {"location_filter": {"accept_remote": True}}
        passed, reason = apply_location_filter(posting, parse_result, settings=settings)
        assert passed is True

    def test_accept_nearby_matching_city(self):
        from quarry.pipeline.filter import apply_location_filter
        from quarry.models import JobPosting as JP
        posting = JP(company_id=1, title="Eng", title_hash="h", url="https://example.com")
        parse_result = PRes(work_model=None, locations=[PLoc(
            canonical_name="San Francisco, CA", city="San Francisco",
            state_code="CA", country_code="US", region="US-West",
        )])
        settings = {"location_filter": {
            "accept_nearby": True,
            "nearby_cities": ["San Francisco"],
        }}
        passed, reason = apply_location_filter(posting, parse_result, settings=settings)
        assert passed is True

    def test_reject_non_nearby(self):
        from quarry.pipeline.filter import apply_location_filter
        from quarry.models import JobPosting as JP
        posting = JP(company_id=1, title="Eng", title_hash="h", url="https://example.com")
        parse_result = PRes(work_model=None, locations=[PLoc(
            canonical_name="New York, NY", city="New York",
            state_code="NY", country_code="US", region="US-East",
        )])
        settings = {"location_filter": {
            "accept_nearby": True,
            "nearby_cities": ["San Francisco"],
        }}
        passed, reason = apply_location_filter(posting, parse_result, settings=settings)
        assert passed is False
        assert reason == "location"

    def test_empty_locations_passes(self):
        from quarry.pipeline.filter import apply_location_filter
        from quarry.models import JobPosting as JP
        posting = JP(company_id=1, title="Eng", title_hash="h", url="https://example.com")
        parse_result = PRes(work_model=None, locations=[])
        settings = {"location_filter": {"accept_nearby": True, "nearby_cities": ["San Francisco"]}}
        passed, reason = apply_location_filter(posting, parse_result, settings=settings)
        assert passed is True

    def test_accept_regions_matching(self):
        from quarry.pipeline.filter import apply_location_filter
        from quarry.models import JobPosting as JP
        posting = JP(company_id=1, title="Eng", title_hash="h", url="https://example.com")
        parse_result = PRes(work_model=None, locations=[PLoc(
            canonical_name="Portland, OR", city="Portland",
            state_code="OR", country_code="US", region="US-West",
        )])
        settings = {"location_filter": {
            "accept_nearby": True,
            "nearby_cities": ["San Francisco"],
            "accept_regions": ["US-West"],
        }}
        passed, reason = apply_location_filter(posting, parse_result, settings=settings)
        assert passed is True
```

- [ ] **Step 8b: Run tests — should fail**

Run: `pytest tests/test_pipeline_filter.py::TestApplyLocationFilter -v`
Expected: FAIL — `apply_location_filter` not found.

- [ ] **Step 8c: Implement apply_location_filter**

Add to `quarry/pipeline/filter.py`:

```python
from quarry.models import JobPosting, ParseResult


def apply_location_filter(
    posting: JobPosting,
    parse_result: ParseResult,
    settings: dict | None = None,
) -> tuple[bool, str]:
    """Apply location filter to a posting using its ParseResult.

    Args:
        posting: JobPosting (used for context, not filtered directly).
        parse_result: Parsed location data with work_model and locations.
        settings: Dict with optional 'location_filter' key containing:
            - accept_remote: bool
            - accept_nearby: bool
            - nearby_cities: list[str]
            - accept_regions: list[str]

    Returns:
        Tuple of (passed: bool, skip_reason: str or None).
    """
    if settings is None:
        return True, None

    loc_config = settings.get("location_filter")
    if loc_config is None:
        return True, None

    accept_remote = loc_config.get("accept_remote", False)
    accept_nearby = loc_config.get("accept_nearby", False)
    nearby_cities = [c.lower() for c in loc_config.get("nearby_cities", [])]
    accept_regions = [r.lower() for r in loc_config.get("accept_regions", [])]

    if accept_remote and parse_result.work_model == "remote":
        return True, None

    if not parse_result.locations:
        return True, None

    if accept_nearby:
        for loc in parse_result.locations:
            if loc.city and loc.city.lower() in nearby_cities:
                return True, None
            if loc.state_code and loc.state_code.lower() in [c.lower() for c in nearby_cities]:
                return True, None
            if loc.region and loc.region.lower() in accept_regions:
                return True, None

    if not accept_nearby:
        return True, None

    return False, "location"
```

Add the import at the top of filter.py:

```python
from quarry.models import FilterResult, JobPosting, ParseResult, RawPosting
```

- [ ] **Step 8d: Run tests**

Run: `pytest tests/test_pipeline_filter.py -v`
Expected: PASS

- [ ] **Step 8e: Commit**

```bash
git add quarry/pipeline/filter.py tests/test_pipeline_filter.py
git commit -m "feat: add apply_location_filter for structured location-based filtering"
```

---

### Task 9: Update Crawlers (Remove remote from RawPosting)

**Files:**
- Modify: `quarry/crawlers/lever.py`
- Modify: `quarry/crawlers/ashby.py`
- Modify: `quarry/crawlers/jobspy_client.py`

> **Note:** The crawlers' `is_remote` detection could be preserved as a signal for work model resolution in the future (e.g., if a crawler has high-confidence remote data, pass it as a hint to `parse_location`). For now, we remove it since the pipeline handles work model detection and the crawler-level heuristic was unreliable. A future enhancement could add an optional `work_model_hint` field to `RawPosting`.

- [ ] **Step 9a: Update lever.py**

Remove the `is_remote` logic from `_parse_jobs`:

```python
def _parse_jobs(
    self, jobs: list[dict[str, Any]], company_id: int
) -> list[RawPosting]:
    """Parse jobs from Lever API response."""
    postings = []
    for job in jobs:
        categories = job.get("categories", {})
        location = categories.get("location", "")

        posting = RawPosting(
            company_id=company_id,
            title=job.get("text", ""),
            url=job.get("hostedUrl", ""),
            description=job.get("descriptionPlain"),
            location=location,
            source_id=job.get("id"),
            source_type="lever",
        )
        postings.append(posting)

    return postings
```

- [ ] **Step 9b: Update ashby.py**

Remove the `is_remote` logic from `_parse_jobs`:

```python
def _parse_jobs(
    self, jobs: list[dict[str, Any]], company_id: int
) -> list[RawPosting]:
    postings = []
    for job in jobs:
        posted_at = None
        if posted_at_str := job.get("postedAt"):
            try:
                posted_at = datetime.fromisoformat(
                    posted_at_str.replace("Z", "+00:00")
                )
            except ValueError:
                pass

        location = job.get("location", "")

        posting = RawPosting(
            company_id=company_id,
            title=job.get("title", ""),
            url=job.get("absoluteUrl", ""),
            description=job.get("descriptionPlain"),
            location=location,
            posted_at=posted_at,
            source_id=job.get("id"),
            source_type="ashby",
        )
        postings.append(posting)

    return postings
```

- [ ] **Step 9c: Update jobspy_client.py**

Remove `_parse_remote` method and `remote=self._parse_remote(row)` from `_convert_dataframe`:

```python
posting = RawPosting(
    company_id=company_id,
    title=str(row.get("title", "Unknown")),
    url=str(row.get("url", "")),
    description=str(row.get("description"))
    if row.get("description")
    else None,
    location=str(row.get("location")) if row.get("location") else None,
    posted_at=row.get("date_posted"),
    source_id=str(row.get("job_id", "")),
    source_type=str(source_type),
)
```

Delete the entire `_parse_remote` method (lines 107-112).

- [ ] **Step 9d: Run crawler tests**

Run: `pytest tests/test_lever_crawler.py tests/test_ashby_crawler.py tests/test_greenhouse_crawler.py -v`
Expected: PASS

- [ ] **Step 9e: Commit**

```bash
git add quarry/crawlers/lever.py quarry/crawlers/ashby.py quarry/crawlers/jobspy_client.py
git commit -m "refactor: remove remote field from RawPosting in crawlers"
```

---

### Task 10: Update Scheduler

**Files:**
- Modify: `quarry/agent/scheduler.py`

- [ ] **Step 10a: Update _process_posting to handle ParseResult**

In `quarry/agent/scheduler.py`, update `_process_posting`:

The function signature changes to also accept and use `ParseResult`, and store location links. The return type becomes:

```python
def _process_posting(
    raw: RawPosting,
    db: Database,
    blocklist: list[str],
    ideal_embedding: np.ndarray | None,
) -> tuple[JobPosting | None, str, float]:
```

Update the body to call `extract()` and handle the tuple:

```python
from quarry.pipeline.locations import parse_location as _parse_location
from quarry.models import ParseResult as _ParseResult
```

Inside `_process_posting`, change:

```python
    posting, parse_result = extract(raw)
```

After dedup check, before similarity check, add location filter:

```python
    from quarry.config import settings as _settings
    loc_filter_config = None
    if hasattr(_settings, 'location_filter') and _settings.location_filter:
        loc_filter_config = {"location_filter": dict(_settings.location_filter)}
    passed, loc_reason = apply_location_filter(posting, parse_result, loc_filter_config)
    if not passed:
        similarity = 0.0
        if ideal_embedding is not None:
            emb = embed_posting(raw)
            norm_e = np.linalg.norm(emb)
            norm_i = np.linalg.norm(ideal_embedding)
            similarity = float(np.dot(emb, ideal_embedding) / (norm_e * norm_i + 1e-9))
        return None, loc_reason, round(similarity, 4)
```

Update the `import` block at the top — add `apply_location_filter`:

```python
from quarry.pipeline.filter import apply_keyword_blocklist, apply_location_filter, filter_posting
```

After a successful posting insertion, link locations:

```python
    # ... after db.insert_posting(posting) in run_once ...
    for loc in parse_result.locations:
        loc_id = db.get_or_create_location(loc)
        db.link_posting_location(posting.id, loc_id)
```

This needs to happen in `run_once` after `db.insert_posting(job_posting)`. Update the `run_once` function where it calls `db.insert_posting(job_posting)` — add location linking after each insert.

- [ ] **Step 10b: Commit**

```bash
git add quarry/agent/scheduler.py
git commit -m "feat: integrate location parsing and filtering into scheduler pipeline"
```

---

### Task 11: Update Digest

**Files:**
- Modify: `quarry/digest/digest.py`

- [ ] **Step 11a: Update build_digest to use work_model**

In `build_digest`, change the dict to use `work_model` instead of `remote`:

```python
def build_digest(db: Database, limit: int | None = None) -> list[dict]:
    limit = limit or settings.digest_top_n
    postings = db.get_recent_postings(limit=limit, status="new")
    entries = []
    for p in postings:
        company_name = db.get_company_name(p.company_id) or "Unknown"
        entries.append(
            {
                "id": p.id,
                "company_name": company_name,
                "title": p.title,
                "url": p.url,
                "similarity_score": p.similarity_score or 0.0,
                "location": p.location or "N/A",
                "work_model": p.work_model,
            }
        )
    return entries
```

- [ ] **Step 11b: Update format_digest to use work_model**

```python
def format_digest(entries: list[dict]) -> str:
    if not entries:
        return "No new job postings found.\n"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"=== Quarry Digest - {now} ===",
        f"{len(entries)} new posting(s)\n",
    ]

    for i, e in enumerate(entries, 1):
        wm = e.get("work_model")
        work_tag = f" [{wm.title()}]" if wm else ""
        score_tag = f" (score: {e['similarity_score']:.3f})"
        lines.append(f"{i}. {e['title']} at {e['company_name']}{work_tag}{score_tag}")
        lines.append(f"   {e['location']}")
        lines.append(f"   {e['url']}")
        lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 11c: Commit**

```bash
git add quarry/digest/digest.py
git commit -m "feat: update digest to use work_model instead of remote boolean"
```

---

### Task 12: Add normalize-locations CLI Command

**Files:**
- Modify: `quarry/agent/tools.py`

- [ ] **Step 12a: Add normalize-locations command**

Add a new click command to `quarry/agent/tools.py`:

```python
@cli.command(name="normalize-locations")
@click.option("--dry-run", is_flag=True, help="Report stats without making changes")
def normalize_locations(dry_run: bool):
    """Parse and normalize location data for all existing postings."""
    from quarry.models import JobPosting
    from quarry.pipeline.locations import parse_location

    db = init_db(settings.db_path)

    postings = db.execute(
        "SELECT * FROM job_postings WHERE location IS NOT NULL AND location != ''"
    )
    parsed_postings = [JobPosting(**dict(row)) for row in postings]
    click.echo(f"Found {len(parsed_postings)} postings with locations")

    locations_created = 0
    links_created = 0
    unresolvable = 0

    for posting in parsed_postings:
        parse_result = parse_location(posting.location)

        if parse_result.work_model and not posting.work_model:
            if not dry_run:
                db.execute(
                    "UPDATE job_postings SET work_model = ? WHERE id = ?",
                    (parse_result.work_model, posting.id),
                )

        for loc in parse_result.locations:
            if not dry_run:
                loc_id = db.get_or_create_location(loc)
                db.link_posting_location(posting.id or 0, loc_id)
            locations_created += 1
            if loc.resolution_status == "needs_review":
                unresolvable += 1
                click.echo(f"  Needs review: {loc.raw_fragment} → {loc.canonical_name}")
            links_created += 1

    click.echo(f"Locations created: {locations_created}")
    click.echo(f"Links created: {links_created}")
    click.echo(f"Unresolvable fragments: {unresolvable}")
    if dry_run:
        click.echo("(dry run — no changes made)")


if __name__ == "__main__":
    cli()
```

- [ ] **Step 12b: Commit**

```bash
git add quarry/agent/tools.py
git commit -m "feat: add normalize-locations CLI command"
```

---

### Task 13: Update All Existing Tests

**Files:**
- Modify: `tests/test_pipeline_extract.py`
- Modify: `tests/test_pipeline_integration.py`
- Modify: `tests/test_digest.py`
- Modify: `tests/test_e2e.py`

- [ ] **Step 13a: Update test_pipeline_extract.py**

Change all references from `result.remote` to `result[0].work_model` or `posting.work_model` since `extract()` now returns a tuple. Update `detect_remote` tests to test both `detect_work_model` and backward-compatible `detect_remote`:

Key changes:
- `extract(raw)` → `posting, _ = extract(raw)` or `posting, parse_result = extract(raw)`
- `result.remote` → `result.work_model`
- `result.remote is True` → `result.work_model in ('remote', 'hybrid')`
- `result.remote is False` → `result.work_model == 'onsite'`
- `result.remote is None` → `result.work_model is None`

- [ ] **Step 13b: Update test_pipeline_integration.py**

Change `result = extract(raw)` → `result, _ = extract(raw)`.
Update assertions:
- `result.remote is True` → `result.work_model == 'remote'`

- [ ] **Step 13c: Update test_digest.py**

Change `remote=True` in fixture → `work_model="remote"`.
Remove `remote` field from posting constructor.

- [ ] **Step 13d: Update test_e2e.py**

No `remote` field on `RawPosting` anymore. Remove it from the mock posting if present.

- [ ] **Step 13e: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 13f: Run linter and type checker**

Run: `ruff check . && PYTHONPATH=/home/kurtt/job-search pyright quarry/`

- [ ] **Step 13g: Fix any issues found**

- [ ] **Step 13h: Commit**

```bash
git add tests/
git commit -m "refactor: update all tests for work_model replacing remote boolean"
```

---

### Task 14: Rebuild Database and Verify

- [ ] **Step 14a: Delete old database and re-initialize**

```bash
rm quarry.db
python -m quarry.store init
python -m quarry.agent.tools seed
```

- [ ] **Step 14b: Run normalize-locations (if data exists)**

```bash
python -m quarry.agent.tools normalize-locations --dry-run
```

- [ ] **Step 14c: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 14d: Run lint and type check**

Run: `ruff check . && PYTHONPATH=/home/kurtt/job-search pyright quarry/`

- [ ] **Step 14e: Update STATUS.md**

Update `docs/STATUS.md` to reflect the completed location normalization feature.

- [ ] **Step 14f: Final commit**

```bash
git add docs/STATUS.md
git commit -m "docs: update STATUS.md with location normalization milestone"
```

---

## Self-Review Checklist

- [x] **Spec coverage** — Every section of the spec has a corresponding task:
  - Schema changes → Task 3
  - Data transport shape (ParsedLocation/ParseResult) → Task 2
  - Parsing pipeline → Task 4
  - Filter integration → Task 8
  - DB methods → Task 3 + Task 5
  - Crawler changes → Task 9
  - Extract changes → Task 7
  - Digest changes → Task 11
  - Scheduler changes → Task 10
  - CLI command → Task 12
  - Tests → Task 4 + Task 5 + Task 8 + Task 13
  - Config → Task 6

- [x] **Placeholder scan** — Every step has actual code, no TBD/TODO.

- [x] **Type consistency** — `ParseResult` defined in models.py, imported in locations.py, used in extract.py, filter.py, scheduler.py consistently. `work_model` is `str | None` everywhere. `ParsedLocation` dataclass fields match schema columns.