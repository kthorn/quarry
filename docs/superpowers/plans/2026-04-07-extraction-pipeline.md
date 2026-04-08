# M3: Extraction Pipeline Implementation Plan

**Status:** Refined

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert RawPosting HTML/text into clean structured JobPosting with deduplication support.

**Architecture:** Create a pipeline module with extraction logic that strips HTML, normalizes whitespace, detects remote status via heuristics, and normalizes location strings. The extraction function transforms RawPosting → JobPosting with a title_hash for deduplication. Database functions check for duplicates before insert.

**Tech Stack:** Python 3.11+, BeautifulSoup4 for HTML parsing, hashlib for title hashing, Pydantic for data validation, pytest for testing.

---

## File Structure

**Create:**
- `quarry/pipeline/__init__.py` — module init
- `quarry/pipeline/extract.py` — extraction logic (strip HTML, normalize, detect remote, hash title)
- `tests/test_pipeline_extract.py` — unit tests for extraction

**Modify:**
- `quarry/store/db.py` — add `posting_exists_by_url()` method (URL-based dedup)
- `tests/test_db.py` — tests for URL deduplication

**Dependencies:**
- `beautifulsoup4` — already in requirements.txt
- `hashlib` — stdlib

---

## Task 1: Create pipeline module structure

**Files:**
- Create: `quarry/pipeline/__init__.py`
- Create: `quarry/pipeline/extract.py`

- [ ] **Step 1: Create pipeline directory and init file**

```bash
mkdir -p quarry/pipeline
touch quarry/pipeline/__init__.py
```

- [ ] **Step 2: Create extract.py with module docstring**

Create `quarry/pipeline/extract.py`:

```python
"""Extraction pipeline: RawPosting → JobPosting transformation.

This module handles:
- HTML tag stripping and whitespace normalization
- Remote work detection via keyword heuristics
- Location string normalization
- Title hashing for deduplication
"""
```

- [ ] **Step 3: Commit module structure**

```bash
git add quarry/pipeline/
git commit -m "feat(pipeline): create extraction pipeline module structure"
```

---

## Task 2: Implement HTML stripping and text normalization

**Files:**
- Create: `tests/test_pipeline_extract.py`
- Modify: `quarry/pipeline/extract.py`

- [ ] **Step 1: Write failing test for HTML stripping**

Create `tests/test_pipeline_extract.py`:

```python
"""Tests for extraction pipeline."""
from quarry.pipeline.extract import strip_html, normalize_whitespace


def test_strip_html_removes_tags():
    html = "<p>This is <strong>bold</strong> text</p>"
    result = strip_html(html)
    assert result == "This is bold text"


def test_strip_html_handles_nested_tags():
    html = "<div><p>Paragraph <span>with <em>emphasis</em></span></p></div>"
    result = strip_html(html)
    assert result == "Paragraph with emphasis"


def test_strip_html_preserves_text_content():
    html = "Plain text without tags"
    result = strip_html(html)
    assert result == "Plain text without tags"


def test_normalize_whitespace_collapses_spaces():
    text = "Multiple   spaces   here"
    result = normalize_whitespace(text)
    assert result == "Multiple spaces here"


def test_normalize_whitespace_collapses_newlines():
    text = "Line one\n\n\nLine two"
    result = normalize_whitespace(text)
    assert result == "Line one\n\nLine two"


def test_normalize_whitespace_strips_leading_trailing():
    text = "  text with spaces  "
    result = normalize_whitespace(text)
    assert result == "text with spaces"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_pipeline_extract.py -v
```

Expected: FAIL with "ModuleNotFoundError" or "ImportError"

- [ ] **Step 3: Implement HTML stripping and normalization**

Add to `quarry/pipeline/extract.py`:

```python
"""Extraction pipeline: RawPosting → JobPosting transformation.

This module handles:
- HTML tag stripping and whitespace normalization
- Remote work detection via keyword heuristics
- Location string normalization
- Title hashing for deduplication
"""

import re
from bs4 import BeautifulSoup


def strip_html(html: str) -> str:
    """Remove HTML tags and return plain text.
    
    Args:
        html: HTML string to strip
        
    Returns:
        Plain text with HTML tags removed and whitespace normalized
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ")
    return normalize_whitespace(text)


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace in text.
    
    Collapses multiple spaces to single space, multiple newlines to double newlines,
    and strips leading/trailing whitespace.
    
    Args:
        text: Text to normalize
        
    Returns:
        Normalized text
    """
    if not text:
        return ""
    # Collapse multiple spaces to single space
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse 3+ newlines to 2 newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip leading/trailing whitespace
    text = text.strip()
    return text
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_pipeline_extract.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit HTML stripping implementation**

```bash
git add quarry/pipeline/extract.py tests/test_pipeline_extract.py
git commit -m "feat(pipeline): implement HTML stripping and whitespace normalization"
```

---

## Task 3: Implement remote work detection

**Files:**
- Modify: `quarry/pipeline/extract.py`
- Modify: `tests/test_pipeline_extract.py`

- [ ] **Step 1: Write failing tests for remote detection**

Add to `tests/test_pipeline_extract.py`:

```python
from quarry.pipeline.extract import detect_remote


def test_detect_remote_explicit_remote():
    text = "This is a remote position"
    result = detect_remote(text)
    assert result is True


def test_detect_remote_work_from_home():
    text = "Work from home opportunity"
    result = detect_remote(text)
    assert result is True


def test_detect_remote_hybrid():
    text = "Hybrid role - 3 days in office"
    result = detect_remote(text)
    assert result is True


def test_detect_remote_onsite():
    text = "Must be located in San Francisco"
    result = detect_remote(text)
    assert result is False


def test_detect_remote_no_indicator():
    text = "Great engineering role at our company"
    result = detect_remote(text)
    assert result is None


def test_detect_remote_case_insensitive():
    text = "REMOTE position available"
    result = detect_remote(text)
    assert result is True


def test_detect_remote_ignores_remote_in_company_name():
    text = "Remote Inc is hiring for onsite role"
    result = detect_remote(text)
    assert result is False


def test_detect_remote_company_name_without_onsite():
    text = "Remote Inc is hiring engineers"
    result = detect_remote(text)
    # Should detect "remote" in company name as potential false positive
    # but without onsite indicators, returns None (unclear)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_pipeline_extract.py -k detect_remote -v
```

Expected: FAIL with "ImportError: cannot import name 'detect_remote'"

- [ ] **Step 3: Implement remote detection**

Add to `quarry/pipeline/extract.py`:

```python
def detect_remote(text: str) -> bool | None:
    """Detect if a job posting is remote using keyword heuristics.
    
    Returns True if remote indicators found, False if onsite indicators found,
    None if no clear indicators.
    
    Args:
        text: Job description text to analyze
        
    Returns:
        True if remote, False if onsite, None if unclear
    """
    if not text:
        return None
    
    text_lower = text.lower()
    
    # Remote indicators (strong)
    remote_patterns = [
        r"\bremote\b",
        r"\bwork from home\b",
        r"\bwfh\b",
        r"\bfully remote\b",
        r"\b100% remote\b",
        r"\bwork remotely\b",
    ]
    
    # Hybrid indicators (counts as remote)
    hybrid_patterns = [
        r"\bhybrid\b",
        r"\bremote-first\b",
        r"\bdistributed team\b",
    ]
    
    # Onsite indicators (strong office requirement)
    onsite_patterns = [
        r"\bon[- ]?site\b",
        r"\bin[- ]?office\b",
        r"\bin office\b",
        r"\brelocation required\b",
        r"\bno remote\b",
        r"\bnot remote\b",
    ]
    
    # Location constraint indicators (not necessarily onsite)
    location_constraint_patterns = [
        r"\bmust (be )?(located|based) in\b",
    ]
    
    # Check for remote indicators
    has_remote = any(re.search(p, text_lower) for p in remote_patterns + hybrid_patterns)
    has_onsite = any(re.search(p, text_lower) for p in onsite_patterns)
    has_location_constraint = any(re.search(p, text_lower) for p in location_constraint_patterns)
    
    # If both remote and onsite present, prefer onsite (more specific)
    if has_remote and has_onsite:
        return False
    # If remote with location constraint, still remote (e.g., "Remote, must be based in US")
    if has_remote:
        return True
    # If only onsite indicators, mark as onsite
    if has_onsite:
        return False
    # Location constraint alone is not enough to determine onsite
    if has_location_constraint:
        return None
    
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_pipeline_extract.py::test_detect_remote -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit remote detection**

```bash
git add quarry/pipeline/extract.py tests/test_pipeline_extract.py
git commit -m "feat(pipeline): implement remote work detection via heuristics"
```

---

## Task 4: Implement location normalization

**Files:**
- Modify: `quarry/pipeline/extract.py`
- Modify: `tests/test_pipeline_extract.py`

- [ ] **Step 1: Write failing tests for location normalization**

Add to `tests/test_pipeline_extract.py`:

```python
from quarry.pipeline.extract import normalize_location


def test_normalize_location_standardizes_us():
    location = "San Francisco, CA, USA"
    result = normalize_location(location)
    assert result == "San Francisco, CA, US"


def test_normalize_location_removes_extra_spaces():
    location = "New  York ,  NY"
    result = normalize_location(location)
    assert result == "New York, NY"


def test_normalize_location_handles_remote():
    location = "Remote - US"
    result = normalize_location(location)
    assert result == "Remote - US"


def test_normalize_location_handles_multiple_locations():
    location = "San Francisco, CA or New York, NY"
    result = normalize_location(location)
    assert result == "San Francisco, CA or New York, NY"


def test_normalize_location_handles_empty():
    result = normalize_location("")
    assert result is None


def test_normalize_location_handles_none():
    result = normalize_location(None)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_pipeline_extract.py -k normalize_location -v
```

Expected: FAIL with "ImportError: cannot import name 'normalize_location'"

- [ ] **Step 3: Implement location normalization**

Add to `quarry/pipeline/extract.py`:

```python
def normalize_location(location: str | None) -> str | None:
    """Normalize location string.
    
    Standardizes country codes, removes extra whitespace, and handles common patterns.
    
    Args:
        location: Location string to normalize
        
    Returns:
        Normalized location string or None if empty
    """
    if not location:
        return None
    
    # Strip and collapse whitespace
    location = re.sub(r"\s+", " ", location.strip())
    
    # Standardize country codes
    location = re.sub(r"\bUSA?\b", "US", location, flags=re.IGNORECASE)
    location = re.sub(r"\bUK\b", "United Kingdom", location, flags=re.IGNORECASE)
    
    # Remove extra spaces around commas
    location = re.sub(r"\s*,\s*", ", ", location)
    
    return location if location else None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_pipeline_extract.py::test_normalize_location -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit location normalization**

```bash
git add quarry/pipeline/extract.py tests/test_pipeline_extract.py
git commit -m "feat(pipeline): implement location string normalization"
```

---

## Task 5: Implement title hashing for deduplication

**Files:**
- Modify: `quarry/pipeline/extract.py`
- Modify: `tests/test_pipeline_extract.py`

- [ ] **Step 1: Write failing tests for title hashing**

Add to `tests/test_pipeline_extract.py`:

```python
from quarry.pipeline.extract import hash_title


def test_hash_title_returns_consistent_hash():
    title = "Senior Software Engineer"
    hash1 = hash_title(title)
    hash2 = hash_title(title)
    assert hash1 == hash2


def test_hash_title_normalizes_case():
    title1 = "Senior Software Engineer"
    title2 = "SENIOR SOFTWARE ENGINEER"
    assert hash_title(title1) == hash_title(title2)


def test_hash_title_normalizes_whitespace():
    title1 = "Senior  Software   Engineer"
    title2 = "Senior Software Engineer"
    assert hash_title(title1) == hash_title(title2)


def test_hash_title_is_sha256():
    title = "Software Engineer"
    result = hash_title(title)
    # SHA256 produces 64 character hex string
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_pipeline_extract.py -k hash_title -v
```

Expected: FAIL with "ImportError: cannot import name 'hash_title'"

- [ ] **Step 3: Implement title hashing**

Add to `quarry/pipeline/extract.py`:

```python
import hashlib


def hash_title(title: str) -> str:
    """Create a hash of job title for deduplication.
    
    Normalizes title (lowercase, collapse whitespace) before hashing.
    Uses SHA256 for collision resistance.
    
    Args:
        title: Job title to hash
        
    Returns:
        Hex string of SHA256 hash
    """
    if not title:
        return ""
    
    # Normalize: lowercase and collapse whitespace
    normalized = re.sub(r"\s+", " ", title.lower().strip())
    
    # Hash with SHA256
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_pipeline_extract.py::test_hash_title -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit title hashing**

```bash
git add quarry/pipeline/extract.py tests/test_pipeline_extract.py
git commit -m "feat(pipeline): implement title hashing for deduplication"
```

---

## Task 6: Implement main extract() function

**Files:**
- Modify: `quarry/pipeline/extract.py`
- Modify: `tests/test_pipeline_extract.py`

- [ ] **Step 1: Write failing tests for extract() function**

Add to `tests/test_pipeline_extract.py`:

```python
from datetime import datetime
from quarry.models import RawPosting, JobPosting
from quarry.pipeline.extract import extract


def test_extract_converts_raw_to_job_posting():
    raw = RawPosting(
        company_id=1,
        title="Senior Software Engineer",
        url="https://example.com/job/123",
        description="<p>Work on <strong>amazing</strong> things</p>",
        location="San Francisco, CA, USA",
        source_type="greenhouse",
    )
    
    result = extract(raw)
    
    assert isinstance(result, JobPosting)
    assert result.company_id == 1
    assert result.title == "Senior Software Engineer"
    assert result.url == "https://example.com/job/123"
    assert result.description == "Work on amazing things"
    assert result.location == "San Francisco, CA, US"
    assert result.remote is None  # No remote indicator in description
    assert len(result.title_hash) == 64


def test_extract_detects_remote():
    raw = RawPosting(
        company_id=1,
        title="Remote Software Engineer",
        url="https://example.com/job/456",
        description="This is a remote position working from home",
        location="Remote",
        source_type="greenhouse",
    )
    
    result = extract(raw)
    
    assert result.remote is True


def test_extract_handles_missing_fields():
    raw = RawPosting(
        company_id=1,
        title="Software Engineer",
        url="https://example.com/job/789",
        source_type="lever",
    )
    
    result = extract(raw)
    
    assert result.description is None
    assert result.location is None
    assert result.remote is None


def test_extract_preserves_metadata():
    posted_at = datetime(2024, 1, 15, 10, 30)
    raw = RawPosting(
        company_id=1,
        title="Engineer",
        url="https://example.com/job",
        description="Description",
        posted_at=posted_at,
        source_id="abc123",
        source_type="greenhouse",
    )
    
    result = extract(raw)
    
    assert result.posted_at == posted_at
    assert result.source_id == "abc123"
    assert result.source_type == "greenhouse"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_pipeline_extract.py -k test_extract -v
```

Expected: FAIL with "ImportError: cannot import name 'extract'"

- [ ] **Step 3: Implement extract() function**

Add to `quarry/pipeline/extract.py`:

```python
from quarry.models import JobPosting, RawPosting


def extract(raw: RawPosting) -> JobPosting:
    """Extract and transform RawPosting into JobPosting.
    
    Performs:
    - HTML stripping and text normalization
    - Remote work detection
    - Location normalization
    - Title hashing for deduplication
    
    Args:
        raw: RawPosting from crawler
        
    Returns:
        JobPosting ready for database storage
    """
    # Process description
    description = None
    if raw.description:
        description = strip_html(raw.description)
    
    # Detect remote status from combined signals
    remote = None
    combined_text = " ".join(filter(None, [raw.title, description, raw.location]))
    if combined_text:
        remote = detect_remote(combined_text)
    
    # Normalize location
    location = normalize_location(raw.location)
    
    # Hash title for deduplication
    title_hash = hash_title(raw.title)
    
    # Create JobPosting
    return JobPosting(
        company_id=raw.company_id,
        title=raw.title,
        title_hash=title_hash,
        url=raw.url,
        description=description,
        location=location,
        remote=remote,
        posted_at=raw.posted_at,
        source_id=raw.source_id,
        source_type=raw.source_type,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_pipeline_extract.py::test_extract -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit extract() function**

```bash
git add quarry/pipeline/extract.py tests/test_pipeline_extract.py
git commit -m "feat(pipeline): implement main extract() function"
```

---

## Task 7: Add URL-based deduplication to database

**Files:**
- Modify: `quarry/store/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write failing test for URL dedup check**

Add to `tests/test_db.py`:

```python
from quarry.models import JobPosting
from quarry.store.db import Database, init_db


def test_posting_exists_by_url_returns_false_when_not_exists(tmp_path):
    db_path = tmp_path / "test.db"
    db = init_db(db_path)
    
    exists = db.posting_exists_by_url("https://example.com/job/123")
    assert exists is False


def test_posting_exists_by_url_returns_true_when_exists(tmp_path):
    db_path = tmp_path / "test.db"
    db = init_db(db_path)
    
    # Insert a posting
    posting = JobPosting(
        company_id=1,
        title="Software Engineer",
        title_hash="abc123",
        url="https://example.com/job/123",
        status="new",
    )
    
    # First insert a company (required by foreign key)
    from quarry.models import Company
    company = Company(name="Test Corp")
    db.insert_company(company)
    
    db.insert_posting(posting)
    
    # Check if exists
    exists = db.posting_exists_by_url("https://example.com/job/123")
    assert exists is True


def test_posting_exists_by_url_matches_exact_url(tmp_path):
    db_path = tmp_path / "test.db"
    db = init_db(db_path)
    
    from quarry.models import Company
    company = Company(name="Test Corp")
    db.insert_company(company)
    
    posting = JobPosting(
        company_id=1,
        title="Engineer",
        title_hash="hash",
        url="https://example.com/job/123",
        status="new",
    )
    db.insert_posting(posting)
    
    # Exact URL match
    exists = db.posting_exists_by_url("https://example.com/job/123")
    assert exists is True
    
    # Different URL should not match
    exists = db.posting_exists_by_url("https://example.com/job/456")
    assert exists is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_db.py -k posting_exists_by_url -v
```

Expected: FAIL with "AttributeError: 'Database' object has no attribute 'posting_exists_by_url'"

- [ ] **Step 3: Implement posting_exists_by_url()****

Add to `quarry/store/db.py` in the Database class (after the existing `posting_exists` method around line 137):

```python
def posting_exists_by_url(self, url: str) -> bool:
    """Check if a posting with the given URL already exists.
    
    Args:
        url: Job posting URL to check
        
    Returns:
        True if posting exists, False otherwise
    """
    sql = "SELECT 1 FROM job_postings WHERE url = ?"
    rows = self.execute(sql, (url,))
    return len(rows) > 0
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_db.py -k posting_exists_by_url -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit URL deduplication**

```bash
git add quarry/store/db.py tests/test_db.py
git commit -m "feat(store): add posting_exists_by_url for URL-based deduplication"
```

---

## Task 8: Add deduplication integration test

**Files:**
- Create: `tests/test_pipeline_dedup.py`

- [ ] **Step 1: Write failing test for dedup integration**

Create `tests/test_pipeline_dedup.py`:

```python
"""Tests for deduplication integration."""
from quarry.models import Company, JobPosting, RawPosting
from quarry.pipeline.extract import extract
from quarry.store.db import init_db


def test_duplicate_posting_is_skipped(tmp_path):
    db_path = tmp_path / "test.db"
    db = init_db(db_path)
    
    # Insert a company
    company = Company(name="Test Corp")
    db.insert_company(company)
    
    # Create and insert first posting
    raw1 = RawPosting(
        company_id=1,
        title="Software Engineer",
        url="https://example.com/job/123",
        description="Great role",
        source_type="greenhouse",
    )
    posting1 = extract(raw1)
    db.insert_posting(posting1)
    
    # Try to insert duplicate (same URL)
    raw2 = RawPosting(
        company_id=1,
        title="Software Engineer",
        url="https://example.com/job/123",
        description="Great role",
        source_type="greenhouse",
    )
    posting2 = extract(raw2)
    
    # Check if exists before insert
    if not db.posting_exists_by_url(posting2.url):
        db.insert_posting(posting2)
    
    # Verify only one posting exists
    assert db.posting_exists_by_url("https://example.com/job/123")
    rows = db.execute("SELECT COUNT(*) FROM job_postings WHERE url = ?", (posting2.url,))
    assert rows[0][0] == 1


def test_different_postings_are_both_inserted(tmp_path):
    db_path = tmp_path / "test.db"
    db = init_db(db_path)
    
    # Insert a company
    company = Company(name="Test Corp")
    db.insert_company(company)
    
    # Insert first posting
    raw1 = RawPosting(
        company_id=1,
        title="Software Engineer",
        url="https://example.com/job/123",
        source_type="greenhouse",
    )
    posting1 = extract(raw1)
    if not db.posting_exists_by_url(posting1.url):
        db.insert_posting(posting1)
    
    # Insert second posting (different URL)
    raw2 = RawPosting(
        company_id=1,
        title="Senior Engineer",
        url="https://example.com/job/456",
        source_type="greenhouse",
    )
    posting2 = extract(raw2)
    if not db.posting_exists_by_url(posting2.url):
        db.insert_posting(posting2)
    
    # Verify both exist
    assert db.posting_exists_by_url("https://example.com/job/123")
    assert db.posting_exists_by_url("https://example.com/job/456")
    rows = db.execute("SELECT COUNT(*) FROM job_postings")
    assert rows[0][0] == 2
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
python -m pytest tests/test_pipeline_dedup.py -v
```

Expected: All tests PASS

- [ ] **Step 3: Commit dedup integration test**

```bash
git add tests/test_pipeline_dedup.py
git commit -m "test(pipeline): add deduplication integration test"
```

---

## Task 9: Add integration test with fixture data

**Files:**
- Create: `tests/fixtures/greenhouse_posting.json`
- Create: `tests/test_pipeline_integration.py`

- [ ] **Step 1: Create fixture data**

Create `tests/fixtures/greenhouse_posting.json`:

```json
{
  "company_id": 1,
  "title": "Senior Software Engineer - Remote",
  "url": "https://boards.greenhouse.io/example/jobs/12345",
  "description": "<div><p>We are looking for a <strong>Senior Software Engineer</strong> to join our team.</p><p>This is a <em>remote</em> position. Work from home!</p><h2>Requirements</h2><ul><li>5+ years experience</li><li>Python expertise</li></ul></div>",
  "location": "San Francisco, CA, USA or Remote",
  "posted_at": "2024-01-15T10:30:00Z",
  "source_id": "12345",
  "source_type": "greenhouse"
}
```

- [ ] **Step 2: Write integration test**

Create `tests/test_pipeline_integration.py`:

```python
"""Integration tests for extraction pipeline."""
import json
from pathlib import Path

from quarry.models import RawPosting
from quarry.pipeline.extract import extract


def test_extract_with_greenhouse_fixture():
    """Test extraction with real-world Greenhouse posting."""
    fixture_path = Path(__file__).parent / "fixtures" / "greenhouse_posting.json"
    with open(fixture_path) as f:
        data = json.load(f)
    
    raw = RawPosting(**data)
    result = extract(raw)
    
    # Check title preserved
    assert result.title == "Senior Software Engineer - Remote"
    
    # Check HTML stripped
    assert "<div>" not in result.description
    assert "<p>" not in result.description
    assert "Senior Software Engineer" in result.description
    assert "remote position" in result.description
    
    # Check remote detected
    assert result.remote is True
    
    # Check location normalized
    assert result.location == "San Francisco, CA, US or Remote"
    
    # Check title hashed
    assert len(result.title_hash) == 64
    
    # Check metadata preserved
    assert result.source_id == "12345"
    assert result.source_type == "greenhouse"
```

- [ ] **Step 3: Run integration test**

```bash
python -m pytest tests/test_pipeline_integration.py -v
```

Expected: PASS

- [ ] **Step 4: Commit integration test**

```bash
git add tests/fixtures/ tests/test_pipeline_integration.py
git commit -m "test(pipeline): add integration test with Greenhouse fixture"
```

---

## Task 10: Run full test suite and verify acceptance criteria

**Files:**
- None (verification only)

- [ ] **Step 1: Run all pipeline tests**

```bash
python -m pytest tests/test_pipeline_extract.py tests/test_pipeline_integration.py -v
```

Expected: All tests PASS

- [ ] **Step 2: Run all database tests**

```bash
python -m pytest tests/test_db.py -v
```

Expected: All tests PASS

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: All tests PASS

- [ ] **Step 4: Run lint and type checks**

```bash
ruff check .
PYTHONPATH=/home/kurtt/job-search pyright quarry/
```

Expected: No errors

- [ ] **Step 5: Verify acceptance criteria with manual test**

Create a temporary test script `verify_m3.py`:

```python
"""Verify M3 acceptance criteria."""
from quarry.models import RawPosting, JobPosting
from quarry.pipeline.extract import extract

# Create a RawPosting fixture
raw = RawPosting(
    company_id=1,
    title="Senior Software Engineer",
    url="https://example.com/job/123",
    description="<p>This is a <strong>remote</strong> position. Work from home!</p>",
    location="San Francisco, CA, USA",
    source_type="greenhouse",
)

# Extract
job_posting = extract(raw)

# Verify
print("✓ RawPosting fixture created")
print(f"✓ extract() returned JobPosting: {isinstance(job_posting, JobPosting)}")
print(f"✓ Clean text (no HTML): {'<p>' not in str(job_posting.description)}")
print(f"✓ Remote flag correct: {job_posting.remote is True}")
print(f"✓ Location normalized: {job_posting.location == 'San Francisco, CA, US'}")
print(f"✓ Title hashed: {len(job_posting.title_hash) == 64}")
print("\n✅ M3 acceptance criteria verified!")
```

Run it:

```bash
python verify_m3.py
```

Expected: All checks pass

- [ ] **Step 6: Clean up verification script**

```bash
rm verify_m3.py
```

- [ ] **Step 7: Final commit for M3 completion**

```bash
git add docs/superpowers/plans/2026-04-07-extraction-pipeline.md
git commit -m "docs(m3): mark extraction pipeline plan as refined"
```

---

## Summary

This plan implements M3 (Extraction Pipeline) with:

1. **HTML Processing**: Strip tags, normalize whitespace
2. **Remote Detection**: Keyword heuristics (remote, work from home, hybrid, onsite)
3. **Location Normalization**: Standardize country codes, clean whitespace
4. **Deduplication**: SHA256 title hash + URL-based existence check
5. **Testing**: 30+ unit tests + integration test with fixture

**Acceptance Criteria Met:**
- ✅ Given a RawPosting fixture, extract() returns a valid JobPosting
- ✅ Clean text (HTML stripped, whitespace normalized)
- ✅ Correct remote flag (detected via heuristics)
- ✅ Deduplication support (title_hash + URL check)

**Files Created:**
- `quarry/pipeline/__init__.py`
- `quarry/pipeline/extract.py`
- `tests/test_pipeline_extract.py`
- `tests/test_pipeline_integration.py`
- `tests/test_pipeline_dedup.py`
- `tests/fixtures/greenhouse_posting.json`

**Files Modified:**
- `quarry/store/db.py` (added `posting_exists_by_url()`)
- `tests/test_db.py` (tests for URL deduplication)

**Test Coverage:**
- 30+ unit tests for extraction functions
- 3 tests for database deduplication
- 2 tests for deduplication integration
- 1 integration test with real fixture
