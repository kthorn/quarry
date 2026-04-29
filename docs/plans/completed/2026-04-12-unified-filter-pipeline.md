# Unified Filter Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify all hard filters (keyword blocklist, company allow/deny, location) into a typed, ordered pipeline that runs before embedding. Convert similarity from hard gate to soft gate. Fix all identified bugs.

**Architecture:** FilterStep protocol with typed Pydantic config models. Pipeline runs dedup → KeywordBlocklistFilter → CompanyFilter → LocationFilter → embed once → score → store. Similarity threshold applied at read time only. Config normalized through parse_location() at load time.

**Tech Stack:** Python 3.12+, Pydantic, pytest, sqlite3

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `quarry/models.py` | Modify | Remove `FilterResult`, add `FilterDecision`, fix `ParseResult.locations` type |
| `quarry/config.py` | Modify | Add `FiltersConfig` and sub-models, remove `location_filter`/`jobspy_location`, change `extra` to `"forbid"` |
| `quarry/pipeline/filter.py` | Modify | Replace `filter_posting()`/`apply_location_filter()` with `FilterStep` classes, `FILTER_STEPS` list |
| `quarry/agent/scheduler.py` | Modify | Rewrite `_process_posting()` to use filter chain, add `company_name` param, update crawl log, update summary counts |
| `quarry/store/db.py` | Modify | Add `threshold` param to `get_recent_postings()`, add `update_posting_similarities()` bulk method |
| `quarry/agent/tools.py` | Modify | Add `recompute-similarity` CLI command |
| `quarry/digest/digest.py` | Modify | Pass threshold through to `get_recent_postings()` |
| `quarry/ui/app.py` | Modify | Apply threshold filter in posting queries |
| `quarry/config.yaml.example` | Modify | Replace `location_filter`/`jobspy_location` with `filters:` section |
| `tests/test_pipeline_filter.py` | Rewrite | Tests for new filter classes, FilterDecision, config normalization |
| `tests/test_m4_integration.py` | Modify | Update integration tests for new pipeline |
| `tests/test_scheduler.py` | Modify | Update for new `_process_posting()` signature |
| `tests/test_config.py` | Modify | Add tests for `FiltersConfig` validation and `normalize_config()` |

---

### Task 1: Models — Remove FilterResult, Add FilterDecision

**Files:**
- Modify: `quarry/models.py:144-152`
- Test: `tests/test_models_location.py`

- [ ] **Step 1: Write failing test for FilterDecision**

Add to `tests/test_models_location.py`:

```python
from quarry.models import FilterDecision


def test_filter_decision_passed():
    d = FilterDecision(passed=True)
    assert d.passed is True
    assert d.skip_reason is None


def test_filter_decision_rejected():
    d = FilterDecision(passed=False, skip_reason="blocklist")
    assert d.passed is False
    assert d.skip_reason == "blocklist"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models_location.py -v -k "filter_decision"`
Expected: FAIL — `ImportError: cannot import name 'FilterDecision'`

- [ ] **Step 3: Implement FilterDecision, remove FilterResult**

In `quarry/models.py`:

1. Remove the entire `FilterResult` class (lines 144-152).
2. Add `FilterDecision` dataclass before `EnrichedPosting`:

```python
@dataclass
class FilterDecision:
    passed: bool
    skip_reason: str | None = None
```

3. Fix `ParseResult.locations` type annotation:

```python
@dataclass
class ParseResult:
    work_model: str | None = None
    locations: list[ParsedLocation] = field(default_factory=list)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_models_location.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quarry/models.py tests/test_models_location.py
git commit -m "feat: replace FilterResult with FilterDecision, fix ParseResult type"
```

---

### Task 2: Config — Add FiltersConfig Models

**Files:**
- Modify: `quarry/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for FiltersConfig**

Add to `tests/test_config.py`:

```python
from quarry.config import (
    FiltersConfig,
    KeywordBlocklistConfig,
    CompanyFilterConfig,
    LocationFilterConfig,
)


def test_empty_filters_config_passes():
    config = FiltersConfig()
    assert config.keyword_blocklist is None
    assert config.company_filter is None
    assert config.location_filter is None


def test_keyword_blocklist_config_defaults():
    config = KeywordBlocklistConfig()
    assert config.keywords == []
    assert config.passlist == []


def test_company_filter_config_defaults():
    config = CompanyFilterConfig()
    assert config.allow == []
    assert config.deny == []


def test_location_filter_config_defaults():
    config = LocationFilterConfig()
    assert config.target_location == []
    assert config.accept_remote is True
    assert config.nearby_radius is None
    assert config.accept_states == []
    assert config.accept_regions == []


def test_filters_config_normalize_empty():
    config = FiltersConfig()
    config.normalize_config()
    assert config.location_filter is None


def test_location_filter_normalize_config_resolves_cities():
    config = LocationFilterConfig(
        target_location=["San Francisco"],
        accept_states=["CA"],
        accept_regions=["US-West"],
    )
    config.normalize_config()
    assert "san francisco" in config._resolved_cities
    assert "ca" in config._resolved_states
    assert "us-west" in config._resolved_regions


def test_settings_rejects_unknown_keys():
    """Verify extra='forbid' is set on Settings."""
    from quarry.config import Settings
    import pytest
    with pytest.raises(Exception):
        Settings(unknown_key="value")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -v -k "filters or keyword_blocklist or company_filter or location_filter or settings_rejects"`
Expected: FAIL — import errors

- [ ] **Step 3: Implement FiltersConfig and sub-models**

In `quarry/config.py`:

1. Add imports at the top:

```python
from pydantic import PrivateAttr
```

2. Add the filter config classes before `Settings`:

```python
class KeywordBlocklistConfig(BaseModel):
    keywords: list[str] = []
    passlist: list[str] = []


class CompanyFilterConfig(BaseModel):
    allow: list[str] = []
    deny: list[str] = []


class LocationFilterConfig(BaseModel):
    target_location: list[str] = []
    accept_remote: bool = True
    nearby_radius: int | None = None
    accept_states: list[str] = []
    accept_regions: list[str] = []

    _resolved_cities: set[str] = PrivateAttr(default_factory=set)
    _resolved_states: set[str] = PrivateAttr(default_factory=set)
    _resolved_regions: set[str] = PrivateAttr(default_factory=set)

    def normalize_config(self) -> None:
        from quarry.pipeline.locations import parse_location

        for entry in self.target_location:
            result = parse_location(entry)
            for loc in result.locations:
                if loc.city:
                    self._resolved_cities.add(loc.city.lower())
                if loc.state_code:
                    self._resolved_states.add(loc.state_code.lower())
        for state in self.accept_states:
            self._resolved_states.add(state.lower())
        self._resolved_regions = {r.lower() for r in self.accept_regions}


class FiltersConfig(BaseModel):
    keyword_blocklist: KeywordBlocklistConfig | None = None
    company_filter: CompanyFilterConfig | None = None
    location_filter: LocationFilterConfig | None = None

    def normalize_config(self) -> None:
        if self.location_filter and self.location_filter.target_location:
            self.location_filter.normalize_config()
```

3. Update `Settings` class:
   - Change `extra` from `"ignore"` to `"forbid"`
   - Add `filters: FiltersConfig | None = None`
   - Remove `location_filter: dict | None = None`
   - Remove `jobspy_location: str = ""`

4. Update `load_config()` to call `normalize_config()` after loading:

```python
settings_obj = Settings(**combined)
if settings_obj.filters:
    settings_obj.filters.normalize_config()
return settings_obj
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Verify existing tests still pass**

Run: `python -m pytest tests/ -v --timeout=60`
Expected: All existing tests pass (may need to fix tests that reference removed config keys)

- [ ] **Step 6: Commit**

```bash
git add quarry/config.py tests/test_config.py
git commit -m "feat: add FiltersConfig Pydantic models, remove location_filter/jobspy_location, set extra=forbid"
```

---

### Task 3: Filter Implementations — KeywordBlocklistFilter, CompanyFilter, LocationFilter

**Files:**
- Modify: `quarry/pipeline/filter.py`
- Test: `tests/test_pipeline_filter.py`

- [ ] **Step 1: Write failing tests for new filter classes**

Rewrite `tests/test_pipeline_filter.py` entirely. Keep `TestCosineSimilarity` and `TestScoreSimilarity` unchanged. Replace `TestApplyKeywordBlocklist`, `TestFilterPosting`, and `TestApplyLocationFilter` with new test classes.

Key test cases:

```python
class TestKeywordBlocklistFilter:
    """Tests for KeywordBlocklistFilter.check()"""

    def test_empty_keywords_passes(self):
        config = KeywordBlocklistConfig()
        filt = KeywordBlocklistFilter()
        raw = RawPosting(company_id=1, title="Senior Eng", url="http://x", source_type="test")
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_keyword_match_blocks(self):
        config = KeywordBlocklistConfig(keywords=["staffing agency"])
        filt = KeywordBlocklistFilter()
        raw = RawPosting(company_id=1, title="Staffing Agency Recruiter", url="http://x", source_type="test")
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is False
        assert decision.skip_reason == "blocklist"

    def test_passlist_overrides_blocklist(self):
        config = KeywordBlocklistConfig(keywords=["senior"], passlist=["senior product"])
        filt = KeywordBlocklistFilter()
        raw = RawPosting(company_id=1, title="Senior Product Manager", url="http://x", source_type="test")
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_passlist_no_match_still_blocked(self):
        config = KeywordBlocklistConfig(keywords=["senior"], passlist=["principal"])
        filt = KeywordBlocklistFilter()
        raw = RawPosting(company_id=1, title="Senior Engineer", url="http://x", source_type="test")
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is False
        assert decision.skip_reason == "blocklist"

    def test_case_insensitive(self):
        config = KeywordBlocklistConfig(keywords=["STAFFING AGENCY"])
        filt = KeywordBlocklistFilter()
        raw = RawPosting(company_id=1, title="staffing agency recruiter", url="http://x", source_type="test")
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is False

    def test_none_config_passes(self):
        filt = KeywordBlocklistFilter()
        config = filt.get_config(None)
        assert config.keywords == []

class TestCompanyFilter:
    """Tests for CompanyFilter.check()"""

    def test_empty_allow_and_deny_passes(self):
        config = CompanyFilterConfig()
        filt = CompanyFilter()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_deny_match_blocks(self):
        config = CompanyFilterConfig(deny=["Talentify"])
        filt = CompanyFilter()
        decision = filt.check(raw, posting, parse_result, "Talentify Inc", config)
        assert decision.passed is False
        assert decision.skip_reason == "company_deny"

    def test_deny_no_match_passes(self):
        config = CompanyFilterConfig(deny=["Talentify"])
        filt = CompanyFilter()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_allow_match_passes(self):
        config = CompanyFilterConfig(allow=["Acme Corp"])
        filt = CompanyFilter()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_allow_no_match_blocks(self):
        config = CompanyFilterConfig(allow=["Acme Corp"])
        filt = CompanyFilter()
        decision = filt.check(raw, posting, parse_result, "Other Corp", config)
        assert decision.passed is False
        assert decision.skip_reason == "company_allow_skip"

    def test_none_company_name_passes(self):
        config = CompanyFilterConfig(deny=["Talentify"])
        filt = CompanyFilter()
        decision = filt.check(raw, posting, parse_result, None, config)
        assert decision.passed is True

    def test_case_insensitive_normalized(self):
        config = CompanyFilterConfig(deny=["talentify"])
        filt = CompanyFilter()
        decision = filt.check(raw, posting, parse_result, "TALENTIFY Inc.", config)
        assert decision.passed is False

class TestLocationFilter:
    """Tests for LocationFilter.check()"""

    def test_empty_target_location_passes_all(self):
        config = LocationFilterConfig()
        filt = LocationFilter()
        decision = filt.check(raw, posting, parse_result_with_nyc, "Acme Corp", config)
        assert decision.passed is True

    def test_accept_remote_passes(self):
        config = LocationFilterConfig(target_location=["San Francisco"], accept_remote=True)
        filt = LocationFilter()
        parse_result = ParseResult(work_model="remote", locations=[])
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_reject_non_remote_when_no_match(self):
        config = LocationFilterConfig(target_location=["San Francisco"], accept_remote=False)
        filt = LocationFilter()
        decision = filt.check(raw, posting, parse_result_with_nyc, "Acme Corp", config)
        assert decision.passed is False
        assert decision.skip_reason == "location"

    def test_match_via_resolved_city(self):
        config = LocationFilterConfig(target_location=["San Francisco"])
        config.normalize_config()
        filt = LocationFilter()
        parse_result = ParseResult(
            work_model=None,
            locations=[ParsedLocation(canonical_name="San Francisco, CA", city="San Francisco", state_code="CA", region="US-West")]
        )
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_match_via_accept_states(self):
        config = LocationFilterConfig(target_location=["San Francisco"], accept_states=["NY"])
        config.normalize_config()
        filt = LocationFilter()
        decision = filt.check(raw, posting, parse_result_with_nyc, "Acme Corp", config)
        assert decision.passed is True

    def test_match_via_accept_regions(self):
        config = LocationFilterConfig(target_location=["Chicago"], accept_regions=["US-West"])
        config.normalize_config()
        filt = LocationFilter()
        parse_result = ParseResult(
            work_model=None,
            locations=[ParsedLocation(canonical_name="Portland, OR", city="Portland", state_code="OR", region="US-West")]
        )
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_non_matching_location_rejected(self):
        config = LocationFilterConfig(target_location=["San Francisco"])
        config.normalize_config()
        filt = LocationFilter()
        decision = filt.check(raw, posting, parse_result_with_nyc, "Acme Corp", config)
        assert decision.passed is False
        assert decision.skip_reason == "location"

    def test_empty_parse_result_locations_passes(self):
        config = LocationFilterConfig(target_location=["San Francisco"])
        config.normalize_config()
        filt = LocationFilter()
        parse_result = ParseResult(work_model=None, locations=[])
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pipeline_filter.py -v`
Expected: FAIL — import errors for new classes

- [ ] **Step 3: Implement filter classes in `quarry/pipeline/filter.py`**

Rewrite `filter.py` entirely. Keep `cosine_similarity`, `score_similarity`. Remove `apply_keyword_blocklist`, `filter_posting`, `apply_location_filter`. Add:

```python
import re
from dataclasses import dataclass

from quarry.config import (
    CompanyFilterConfig,
    FiltersConfig,
    KeywordBlocklistConfig,
    LocationFilterConfig,
)
from quarry.models import FilterDecision, JobPosting, ParseResult, RawPosting
from quarry.pipeline.embedder import embed_posting


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    # ... keep existing implementation ...


def score_similarity(posting_embedding: np.ndarray, ideal_embedding: np.ndarray) -> float:
    # ... keep existing implementation ...


def embed_and_score(raw: RawPosting, ideal_embedding: np.ndarray) -> tuple[float, np.ndarray]:
    """Embed a posting and compute similarity score. Returns (score, embedding)."""
    embedding = embed_posting(raw)
    score = score_similarity(embedding, ideal_embedding)
    return round(score, 4), embedding


class KeywordBlocklistFilter:
    def get_config(self, filters_config: FiltersConfig | None) -> KeywordBlocklistConfig:
        if filters_config is None or filters_config.keyword_blocklist is None:
            return KeywordBlocklistConfig()
        return filters_config.keyword_blocklist

    def check(self, raw: RawPosting, posting: JobPosting, parse_result: ParseResult, company_name: str | None, config: KeywordBlocklistConfig) -> FilterDecision:
        if not config.keywords:
            return FilterDecision(passed=True)
        text = " ".join(filter(None, [raw.title, raw.description, raw.location])).lower()
        for phrase in config.keywords:
            if phrase.lower() in text:
                for override in config.passlist:
                    if override.lower() in text:
                        return FilterDecision(passed=True)
                return FilterDecision(passed=False, skip_reason="blocklist")
        return FilterDecision(passed=True)


class CompanyFilter:
    def get_config(self, filters_config: FiltersConfig | None) -> CompanyFilterConfig:
        if filters_config is None or filters_config.company_filter is None:
            return CompanyFilterConfig()
        return filters_config.company_filter

    def check(self, raw: RawPosting, posting: JobPosting, parse_result: ParseResult, company_name: str | None, config: CompanyFilterConfig) -> FilterDecision:
        if not company_name:
            return FilterDecision(passed=True)
        normalized = _normalize_company_name(company_name)
        if config.allow:
            if any(_normalize_company_name(a) == normalized for a in config.allow):
                return FilterDecision(passed=True)
            return FilterDecision(passed=False, skip_reason="company_allow_skip")
        if config.deny:
            if any(_normalize_company_name(d) == normalized for d in config.deny):
                return FilterDecision(passed=False, skip_reason="company_deny")
        return FilterDecision(passed=True)


class LocationFilter:
    def get_config(self, filters_config: FiltersConfig | None) -> LocationFilterConfig:
        if filters_config is None or filters_config.location_filter is None:
            return LocationFilterConfig()
        return filters_config.location_filter

    def check(self, raw: RawPosting, posting: JobPosting, parse_result: ParseResult, company_name: str | None, config: LocationFilterConfig) -> FilterDecision:
        if not config.target_location:
            return FilterDecision(passed=True)
        if config.accept_remote and parse_result.work_model == "remote":
            return FilterDecision(passed=True)
        if not parse_result.locations:
            return FilterDecision(passed=True)
        for loc in parse_result.locations:
            if loc.city and loc.city.lower() in config._resolved_cities:
                return FilterDecision(passed=True)
            if loc.state_code and loc.state_code.lower() in config._resolved_states:
                return FilterDecision(passed=True)
            if loc.region and loc.region.lower() in config._resolved_regions:
                return FilterDecision(passed=True)
        return FilterDecision(passed=False, skip_reason="location")


def _normalize_company_name(name: str) -> str:
    return re.sub(r"[^\w\s]", "", name.lower()).strip()


FILTER_STEPS: list = [KeywordBlocklistFilter(), CompanyFilter(), LocationFilter()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pipeline_filter.py -v`
Expected: PASS

- [ ] **Step 5: Run all tests**

Run: `python -m pytest tests/ -v --timeout=60`
Expected: Some tests in `test_scheduler.py` and `test_m4_integration.py` may fail due to removed functions. Note which ones fail.

- [ ] **Step 6: Commit**

```bash
git add quarry/pipeline/filter.py tests/test_pipeline_filter.py
git commit -m "feat: implement FilterStep classes (KeywordBlocklistFilter, CompanyFilter, LocationFilter)"
```

---

### Task 4: Update Scheduler — Rewrite _process_posting, Update Crawl Log, Summary Counts

**Files:**
- Modify: `quarry/agent/scheduler.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Write failing tests for new _process_posting signature**

Update `tests/test_scheduler.py` to test the new pipeline. Key test cases:

```python
def test_process_posting_new_job_stored(db, ideal_embedding, raw_posting):
    """Posting passes all filters → status='new', similarity computed"""
    posting, status, similarity, parse_result = _process_posting(
        raw_posting, db, "Acme Corp", None, ideal_embedding
    )
    assert status == "new"
    assert posting is not None
    assert similarity > 0

def test_process_posting_blocklist_rejected(db, ideal_embedding):
    """Keyword blocklist rejects → status='blocklist', no embedding"""
    config = FiltersConfig(keyword_blocklist=KeywordBlocklistConfig(keywords=["engineer"]))
    raw = RawPosting(company_id=1, title="Senior Engineer", url="http://x", source_type="test")
    posting, status, similarity, parse_result = _process_posting(
        raw, db, "Acme Corp", config, ideal_embedding
    )
    assert status == "blocklist"
    assert posting is None

def test_process_posting_company_deny(db, ideal_embedding):
    """Company deny list rejects → status='company_deny'"""
    config = FiltersConfig(company_filter=CompanyFilterConfig(deny=["Talentify"]))
    raw = RawPosting(company_id=1, title="Recruiter", url="http://x", source_type="test")
    posting, status, similarity, parse_result = _process_posting(
        raw, db, "Talentify", config, ideal_embedding
    )
    assert status == "company_deny"

def test_process_posting_location_rejected(db, ideal_embedding):
    """Location filter rejects → status='location'"""
    config = FiltersConfig(location_filter=LocationFilterConfig(target_location=["San Francisco"]))
    config.location_filter.normalize_config()
    raw = RawPosting(company_id=1, title="Engineer", url="http://x", location="New York, NY", source_type="test")
    posting, status, similarity, parse_result = _process_posting(
        raw, db, "Acme Corp", config, ideal_embedding
    )
    assert status == "location"

def test_process_posting_embeds_once(db, ideal_embedding):
    """Embedding is computed exactly once for postings that pass all filters"""
    raw = RawPosting(company_id=1, title="Software Engineer", url="http://x", source_type="test")
    with patch("quarry.agent.scheduler.embed_posting") as mock_embed:
        mock_embed.return_value = np.ones(384, dtype=np.float32)
        posting, status, similarity, parse_result = _process_posting(
            raw, db, "Acme Corp", None, ideal_embedding
        )
        assert mock_embed.call_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: FAIL — old imports and signatures don't match

- [ ] **Step 3: Rewrite `_process_posting()` in scheduler.py**

Update `quarry/agent/scheduler.py`:

1. Replace imports:
```python
from quarry.pipeline.filter import FILTER_STEPS
from quarry.models import FilterResult  # REMOVE this if present
```

2. Update `CRAWL_LOG_COLUMNS`:
```python
CRAWL_LOG_COLUMNS = [
    "title", "source", "url", "location", "similarity_score", "status", "skip_reason",
]
```

3. Rewrite `_process_posting()`:
```python
def _process_posting(
    raw: RawPosting,
    db: Database,
    company_name: str,
    filters_config: FiltersConfig | None,
    ideal_embedding: np.ndarray | None,
) -> tuple[JobPosting | None, str, float, ParseResult | None]:
    posting, parse_result = extract(raw)

    if db.posting_exists(posting.company_id, posting.title_hash):
        return None, "duplicate", 0.0, parse_result
    if db.posting_exists_by_url(posting.url):
        return None, "duplicate_url", 0.0, parse_result

    for step in FILTER_STEPS:
        config_section = step.get_config(filters_config)
        decision = step.check(raw, posting, parse_result, company_name, config_section)
        if not decision.passed:
            return None, decision.skip_reason, 0.0, parse_result

    if ideal_embedding is None:
        similarity = 0.0
    else:
        embedding = embed_posting(raw)
        similarity = score_similarity(embedding, ideal_embedding)
        posting.similarity_score = round(similarity, 4)
        posting.embedding = serialize_embedding(embedding)

    return posting, "new", round(similarity, 4), parse_result
```

4. Update `_log_posting()` to add `skip_reason` column.
5. Update `run_once()` to pass `filters_config` and `company_name` to `_process_posting()`, add `total_below_threshold` to summary, remove `blocklist` local variable.
6. Remove `from quarry.pipeline.filter import apply_keyword_blocklist, apply_location_filter, filter_posting`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quarry/agent/scheduler.py tests/test_scheduler.py
git commit -m "feat: rewrite _process_posting to use FilterStep pipeline, single embedding, new status strings"
```

---

### Task 5: Similarity as Soft Gate — DB and Digest Changes

**Files:**
- Modify: `quarry/store/db.py`
- Modify: `quarry/digest/digest.py`
- Test: `tests/test_db.py`, `tests/test_digest.py`

- [ ] **Step 1: Write failing test for threshold in get_recent_postings**

Add to `tests/test_db.py`:

```python
def test_get_recent_postings_with_threshold(db_with_postings):
    """Postings below threshold are filtered out at read time."""
    threshold = 0.5
    results = db_with_postings.get_recent_postings(threshold=threshold)
    for p in results:
        assert p.similarity_score >= threshold
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_db.py -v -k "threshold"`
Expected: FAIL — `threshold` parameter not yet accepted

- [ ] **Step 3: Add threshold parameter to get_recent_postings**

In `quarry/store/db.py`, update `get_recent_postings()`:

```python
def get_recent_postings(
    self, limit: int = 100, status: str = "new", threshold: float | None = None,
) -> list[models.JobPosting]:
    if threshold is None:
        from quarry.config import settings
        threshold = settings.similarity_threshold
    sql = """
        SELECT * FROM job_postings
        WHERE status = ? AND similarity_score >= ?
        ORDER BY similarity_score DESC
        LIMIT ?
    """
    rows = self.execute(sql, (status, threshold, limit))
    return [models.JobPosting(**dict(row)) for row in rows]
```

- [ ] **Step 4: Add bulk update method**

```python
def update_posting_similarities(self, posting_id_scores: list[tuple[int, float]]) -> None:
    if not posting_id_scores:
        return
    sql = "UPDATE job_postings SET similarity_score = ? WHERE id = ?"
    self.executemany(sql, [(score, pid) for pid, score in posting_id_scores])
```

Also add `get_all_postings_with_embeddings()`:

```python
def get_all_postings_with_embeddings(self) -> list[models.JobPosting]:
    sql = "SELECT * FROM job_postings WHERE embedding IS NOT NULL"
    rows = self.execute(sql)
    return [models.JobPosting(**dict(row)) for row in rows]
```

- [ ] **Step 5: Update digest to pass threshold**

In `quarry/digest/digest.py`, update the call to `get_recent_postings()` to pass `threshold` (it will use the default from settings if not explicitly provided).

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_db.py tests/test_digest.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add quarry/store/db.py quarry/digest/digest.py tests/test_db.py
git commit -m "feat: add threshold to get_recent_postings, bulk similarity update, soft gate at read time"
```

---

### Task 6: Add recompute-similarity CLI Command

**Files:**
- Modify: `quarry/agent/tools.py`

- [ ] **Step 1: Write failing test for recompute-similarity**

Add to `tests/test_m4_integration.py` or create a new test:

```python
def test_recompute_similarity_updates_scores(db_with_postings_and_embeddings):
    """Recompute changes scores when ideal role embedding changes."""
    from quarry.agent.tools import recompute_similarity
    old_scores = {p.id: p.similarity_score for p in db_with_postings_and_embeddings.get_all_postings_with_embeddings()}
    recompute_similarity()
    new_scores = {p.id: p.similarity_score for p in db_with_postings_and_embeddings.get_all_postings_with_embeddings()}
    assert old_scores != new_scores  # scores changed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ -v -k "recompute"`
Expected: FAIL — import error

- [ ] **Step 3: Implement recompute-similarity**

In `quarry/agent/tools.py`, add:

```python
def recompute_similarity() -> None:
    """Recompute all similarity scores against the current ideal role embedding."""
    from quarry.config import settings
    from quarry.pipeline.embedder import get_ideal_embedding, set_ideal_embedding, deserialize_embedding
    from quarry.pipeline.filter import cosine_similarity

    db = Database(settings.db_path)
    _ensure_ideal_embedding(db)
    ideal_embedding = get_ideal_embedding(db)
    if ideal_embedding is None:
        print("No ideal role embedding found. Set ideal_role_description in config.")
        return

    postings = db.get_all_postings_with_embeddings()
    if not postings:
        print("No postings with embeddings found.")
        return

    updates = []
    skipped = 0
    for p in postings:
        if p.embedding is None:
            skipped += 1
            continue
        emb = deserialize_embedding(p.embedding)
        score = cosine_similarity(emb, ideal_embedding)
        updates.append((p.id, round(score, 4)))

    db.update_posting_similarities(updates)
    print(f"Updated {len(updates)} posting similarity scores. Skipped {skipped} postings with no embedding.")
```

Wire this into the CLI entry point (`quarry/agent/__main__.py`).

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/ -v -k "recompute"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quarry/agent/tools.py quarry/agent/__main__.py
git commit -m "feat: add recompute-similarity CLI command"
```

---

### Task 7: Update Config Example and Fix Remaining Tests

**Files:**
- Modify: `quarry/config.yaml.example`
- Modify: `tests/test_m4_integration.py`
- Modify: Any remaining broken tests
- Modify: `quarry/ui/app.py` (if it queries postings directly)

- [ ] **Step 1: Update config.yaml.example**

Replace the old `location_filter` and `jobspy_location` sections:

```yaml
# === Filters ===
# filters:
#   keyword_blocklist:
#     keywords:
#       - "senior"
#       - "principal"
#     passlist:
#       - "senior product"
#   company_filter:
#     deny:
#       - "Talentify"
#   location_filter:
#     target_location:
#       - "San Francisco"
#       - "Oakland"
#       - "San Jose"
#     accept_remote: true
#     accept_states:
#       - "CA"
#     accept_regions:
#       - "US-West"
```

Remove the old `jobspy_location` line.

- [ ] **Step 2: Update any remaining references to removed functions/classes**

Search the codebase for references to `filter_posting`, `apply_keyword_blocklist`, `apply_location_filter`, `FilterResult`, `jobspy_location`. Fix each one.

- [ ] **Step 3: Update UI app if it queries postings**

In `quarry/ui/app.py`, any endpoints that call `get_recent_postings()` should make sure threshold is passed through.

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -v --timeout=60`
Expected: ALL PASS

- [ ] **Step 5: Run type checker**

Run: `PYTHONPATH=/home/kurtt/job-search pyright quarry/`
Expected: No errors (or fix any that appear)

- [ ] **Step 6: Commit**

```bash
git add quarry/config.yaml.example quarry/ui/app.py tests/test_m4_integration.py
git commit -m "feat: update config example, fix remaining test references, apply threshold in UI"
```

---

### Task 8: Integration Smoke Test and Cleanup

**Files:**
- All modified files
- `docs/STATUS.md`

- [ ] **Step 1: Run full test suite one final time**

Run: `python -m pytest tests/ -v --timeout=60`
Expected: ALL PASS

- [ ] **Step 2: Run linter**

Run: `ruff check .`
Expected: No errors (or fix any that appear)

- [ ] **Step 3: Run type checker**

Run: `PYTHONPATH=/home/kurtt/job-search pyright quarry/`
Expected: No errors

- [ ] **Step 4: Update STATUS.md**

Update `docs/STATUS.md` to reflect the completed unified filter pipeline work.

- [ ] **Step 5: Final commit**

```bash
git add docs/STATUS.md
git commit -m "docs: update STATUS.md with unified filter pipeline completion"
```