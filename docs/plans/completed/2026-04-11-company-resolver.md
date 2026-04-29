# Company Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Resolver Pipeline that derives domain, careers_url, and ATS type for companies created by JobSpy, making them crawlable.

**Architecture:** A `quarry/resolve/` package with three independent, composable resolvers chained in sequence (DomainResolver → CareersUrlResolver → AtsDetector). Each resolver is idempotent (skips companies that already have the field) and persists progress after each step. A shared `httpx.AsyncClient` singleton replaces per-crawler client creation. CLI commands for resolve and add-company integrate the pipeline.

**Tech Stack:** Python 3.12+, httpx (async HTTP), click (CLI), pytest + pytest-asyncio (tests), sqlite3 (DB)

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `quarry/models.py` | Data models — add `resolve_status`, `resolve_attempts` to `Company` | Modify |
| `quarry/store/schema.py` | DB schema — add two new columns to `companies` table | Modify |
| `quarry/store/db.py` | DB methods — `update_company` with new fields, `get_companies_by_resolve_status`, `get_company_by_name`, migration | Modify |
| `quarry/http.py` | Shared `httpx.AsyncClient` singleton | Create |
| `quarry/resolve/__init__.py` | Public API: `resolve_company()`, `resolve_unresolved()` | Create |
| `quarry/resolve/domain_resolver.py` | Company name → domain (guess-and-probe) | Create |
| `quarry/resolve/careers_resolver.py` | Domain → careers_url (URL probing) | Create |
| `quarry/resolve/ats_detector.py` | careers_url → (ats_type, ats_slug) | Create |
| `quarry/resolve/pipeline.py` | Orchestrates resolvers in sequence | Create |
| `quarry/resolve/__main__.py` | CLI: `python -m quarry.resolve [options]` | Create |
| `quarry/store/__main__.py` | CLI: add `add-company` command | Modify |
| `quarry/agent/scheduler.py` | Call `resolve_unresolved()` before crawl loop | Modify |
| `quarry/crawlers/greenhouse.py` | Use shared `http.Client` | Modify |
| `quarry/crawlers/lever.py` | Use shared `http.Client` | Modify |
| `quarry/crawlers/ashby.py` | Use shared `http.Client` | Modify |
| `quarry/crawlers/careers_page.py` | Use shared `http.Client` | Modify |
| `tests/test_http.py` | Tests for shared HTTP client | Create |
| `tests/test_domain_resolver.py` | Tests for domain resolver | Create |
| `tests/test_careers_resolver.py` | Tests for careers URL resolver | Create |
| `tests/test_ats_detector.py` | Tests for ATS detector | Create |
| `tests/test_resolve_pipeline.py` | Tests for pipeline orchestration | Create |
| `tests/test_resolve_cli.py` | Tests for resolve CLI | Create |
| `tests/test_store_cli.py` | Tests for add-company CLI | Create |

---

### Task 1: Company model — add resolve_status and resolve_attempts

**Files:**
- Modify: `quarry/models.py:7-21`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
def test_company_resolve_status_defaults():
    company = Company(name="Test Corp")
    assert company.resolve_status == "unresolved"
    assert company.resolve_attempts == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py::test_company_resolve_status_defaults -v`
Expected: FAIL — `Company` has no field `resolve_status`

- [ ] **Step 3: Add fields to Company model**

In `quarry/models.py`, add two fields after `ats_slug` (after line 13):

```python
    resolve_status: Literal["unresolved", "resolved", "failed"] = "unresolved"
    resolve_attempts: int = 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_models.py::test_company_resolve_status_defaults -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quarry/models.py tests/test_models.py
git commit -m "feat: add resolve_status and resolve_attempts fields to Company model"
```

---

### Task 2: Database schema and methods — add columns, migration, and new queries

**Files:**
- Modify: `quarry/store/schema.py:5-20`
- Modify: `quarry/store/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db.py`:

```python
def test_company_resolve_fields_in_db(tmp_path):
    db = init_db(tmp_path / "test.db")
    company = Company(name="ResolveTest Corp")
    company.id = db.insert_company(company)
    company.resolve_status = "resolved"
    company.resolve_attempts = 2
    db.update_company(company)
    fetched = db.get_company(company.id)
    assert fetched is not None
    assert fetched.resolve_status == "resolved"
    assert fetched.resolve_attempts == 2


def test_get_companies_by_resolve_status(tmp_path):
    db = init_db(tmp_path / "test.db")
    c1 = Company(name="Unresolved Corp")
    c2 = Company(name="Resolved Corp", resolve_status="resolved")
    c3 = Company(name="Failed Corp", resolve_status="failed")
    db.insert_company(c1)
    db.insert_company(c2)
    db.insert_company(c3)
    unresolved = db.get_companies_by_resolve_status("unresolved")
    assert len(unresolved) == 1
    assert unresolved[0].name == "Unresolved Corp"


def test_get_company_by_name(tmp_path):
    db = init_db(tmp_path / "test.db")
    db.insert_company(Company(name="FindMe Corp"))
    found = db.get_company_by_name("FindMe Corp")
    assert found is not None
    assert found.name == "FindMe Corp"
    assert db.get_company_by_name("Nope Corp") is None


def test_migrate_resolve_columns(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE companies (id INTEGER PRIMARY KEY, name TEXT, domain TEXT, careers_url TEXT, "
        "ats_type TEXT DEFAULT 'unknown', ats_slug TEXT, active BOOLEAN DEFAULT TRUE, "
        "crawl_priority INTEGER DEFAULT 5, notes TEXT, added_by TEXT DEFAULT 'seed', "
        "added_reason TEXT, last_crawled_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute("INSERT INTO companies (name) VALUES (?)", ("Old Corp",))
    conn.commit()
    conn.close()

    db = Database(db_path)
    db.migrate_resolve_columns()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM companies WHERE name = 'Old Corp'").fetchone()
    assert row["resolve_status"] == "unresolved"
    assert row["resolve_attempts"] == 0
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db.py::test_company_resolve_fields_in_db tests/test_db.py::test_get_companies_by_resolve_status tests/test_db.py::test_get_company_by_name tests/test_db.py::test_migrate_resolve_columns -v`
Expected: FAIL — methods don't exist, columns missing

- [ ] **Step 3: Add columns to schema**

In `quarry/store/schema.py`, add two columns to the `companies` CREATE TABLE (after `ats_slug TEXT,`):

```sql
    resolve_status TEXT DEFAULT 'unresolved',
    resolve_attempts INTEGER DEFAULT 0,
```

The companies table definition becomes:

```sql
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
```

- [ ] **Step 4: Update `insert_company` to include new fields**

In `quarry/store/db.py`, update `insert_company` to include `resolve_status` and `resolve_attempts`:

```python
    def insert_company(self, company: models.Company) -> int:
        sql = """
            INSERT INTO companies (name, domain, careers_url, ats_type, ats_slug,
                resolve_status, resolve_attempts,
                active, crawl_priority, notes, added_by, added_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                sql,
                (
                    company.name,
                    company.domain,
                    company.careers_url,
                    company.ats_type,
                    company.ats_slug,
                    company.resolve_status,
                    company.resolve_attempts,
                    company.active,
                    company.crawl_priority,
                    company.notes,
                    company.added_by,
                    company.added_reason,
                ),
            )
            return cursor.lastrowid or 0
```

- [ ] **Step 5: Update `update_company` to include new fields**

Replace the `update_company` method in `quarry/store/db.py`:

```python
    def update_company(self, company: models.Company) -> None:
        sql = """
            UPDATE companies SET name=?, domain=?, careers_url=?, ats_type=?,
                ats_slug=?, resolve_status=?, resolve_attempts=?,
                active=?, crawl_priority=?, notes=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """
        self.execute(
            sql,
            (
                company.name,
                company.domain,
                company.careers_url,
                company.ats_type,
                company.ats_slug,
                company.resolve_status,
                company.resolve_attempts,
                company.active,
                company.crawl_priority,
                company.notes,
                company.id,
            ),
        )
```

- [ ] **Step 6: Add `get_companies_by_resolve_status`, `get_company_by_name`, and `migrate_resolve_columns` methods**

Add these methods to `Database` class in `quarry/store/db.py`:

```python
    def get_companies_by_resolve_status(self, status: str) -> list[models.Company]:
        sql = "SELECT * FROM companies WHERE resolve_status = ?"
        rows = self.execute(sql, (status,))
        return [models.Company(**dict(row)) for row in rows]

    def get_company_by_name(self, name: str) -> models.Company | None:
        sql = "SELECT * FROM companies WHERE name = ?"
        rows = self.execute(sql, (name,))
        if rows:
            return models.Company(**dict(rows[0]))
        return None

    def migrate_resolve_columns(self) -> None:
        with self.get_connection() as conn:
            existing = {
                row[1]
                for row in conn.execute("PRAGMA table_info(companies)").fetchall()
            }
            if "resolve_status" not in existing:
                conn.execute(
                    "ALTER TABLE companies ADD COLUMN resolve_status TEXT DEFAULT 'unresolved'"
                )
            if "resolve_attempts" not in existing:
                conn.execute(
                    "ALTER TABLE companies ADD COLUMN resolve_attempts INTEGER DEFAULT 0"
                )
            conn.execute(
                "UPDATE companies SET resolve_status = 'resolved' "
                "WHERE domain IS NOT NULL AND careers_url IS NOT NULL AND ats_type != 'unknown'"
            )
```

- [ ] **Step 7: Call `migrate_resolve_columns` from `init_db`**

In `quarry/store/db.py`, update `init_db`:

```python
def init_db(db_path: str | Path) -> Database:
    """Initialize database with schema."""
    db_path = Path(db_path)
    db = Database(db_path)

    with db.get_connection() as conn:
        conn.executescript(SCHEMA_SQL)

    db.migrate_resolve_columns()

    return db
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest tests/test_db.py -v`
Expected: PASS

- [ ] **Step 9: Run full test suite**

Run: `python -m pytest -v`
Expected: All existing tests still pass

- [ ] **Step 10: Commit**

```bash
git add quarry/store/schema.py quarry/store/db.py tests/test_db.py
git commit -m "feat: add resolve_status and resolve_attempts columns to DB, migration, and query methods"
```

---

### Task 3: Shared HTTP client — quarry/http.py

**Files:**
- Create: `quarry/http.py`
- Create: `tests/test_http.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_http.py`:

```python
import pytest

from quarry.http import close_client, get_client


@pytest.mark.asyncio
async def test_get_client_returns_singleton():
    client1 = get_client()
    client2 = get_client()
    assert client1 is client2
    await close_client()


@pytest.mark.asyncio
async def test_close_client_resets_singleton():
    client1 = get_client()
    await close_client()
    client2 = get_client()
    assert client1 is not client2
    await close_client()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_http.py -v`
Expected: FAIL — module `quarry.http` doesn't exist

- [ ] **Step 3: Write quarry/http.py**

Create `quarry/http.py`:

```python
import httpx

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            ),
            headers={"User-Agent": "Quarry/0.1"},
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_http.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quarry/http.py tests/test_http.py
git commit -m "feat: add shared httpx.AsyncClient singleton in quarry/http.py"
```

---

### Task 4: Domain resolver

**Files:**
- Create: `quarry/resolve/domain_resolver.py`
- Create: `tests/test_domain_resolver.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_domain_resolver.py`:

```python
import pytest

from quarry.models import Company
from quarry.resolve.domain_resolver import normalize_name, resolve_domain


@pytest.mark.asyncio
async def test_resolve_domain_skip_if_already_set():
    company = Company(name="Test", domain="test.com")
    client = None
    result = await resolve_domain(company, client)
    assert result == "test.com"


def test_normalize_name_strips_suffixes():
    assert normalize_name("Acme Inc.") == "acme"
    assert normalize_name("Big Corp LLC") == "big"
    assert normalize_name("Takeda Pharmaceuticals Co.") == "takeda pharmaceuticals"
    assert normalize_name("Global Group Holdings") == "global"
    assert normalize_name("Simple.com") == "simple"
    assert normalize_name("Foo Bar Inc") == "foo bar"


def test_normalize_name_lowercase_and_strip():
    assert normalize_name("  ACME Corp  ") == "acme"


@pytest.mark.asyncio
async def test_resolve_domain_guess_and_probe_success(httpx_mock):
    from quarry.http import close_client, get_client

    httpx_mock.add_response(
        url="https://acme.com", method="HEAD", status_code=200
    )
    client = get_client()
    company = Company(name="Acme Inc.")
    try:
        result = await resolve_domain(company, client)
        assert result == "acme.com"
    finally:
        await close_client()


@pytest.mark.asyncio
async def test_resolve_domain_hyphen_transformation(httpx_mock):
    from quarry.http import close_client, get_client

    httpx_mock.add_response(
        url="https://takeda-pharmaceuticals.com", method="HEAD", status_code=200
    )
    httpx_mock.add_response(
        url="https://takedapharmaceuticals.com", method="HEAD", status_code=404
    )
    client = get_client()
    company = Company(name="Takeda Pharmaceuticals Co.")
    try:
        result = await resolve_domain(company, client)
        assert result == "takeda-pharmaceuticals.com"
    finally:
        await close_client()


@pytest.mark.asyncio
async def test_resolve_domain_returns_none_if_nothing_works(httpx_mock):
    from quarry.http import close_client, get_client

    httpx_mock.add_response(
        url="https://unknownstartup.com", method="HEAD", status_code=404
    )
    client = get_client()
    company = Company(name="UnknownStartup Inc.")
    try:
        result = await resolve_domain(company, client)
        assert result is None
    finally:
        await close_client()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_domain_resolver.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Create the domain resolver package directory**

```bash
mkdir -p /home/kurtt/job-search/quarry/resolve
```

- [ ] **Step 4: Write quarry/resolve/domain_resolver.py**

Create `quarry/resolve/domain_resolver.py`:

```python
import logging
import re

import httpx

from quarry.models import Company

log = logging.getLogger(__name__)

SUFFIXES_TO_STRIP = [
    "inc.", "inc", "llc", "ltd.", "ltd", "co.", "co", "corp.",
    "corp", "group", "holdings", "company", "companies",
]

SUFFIX_RE = re.compile(
    r"\s+(?:inc\.?|llc|ltd\.?|co\.?|corp\.?|group|holdings|company|companies)\s*$",
    re.IGNORECASE,
)


def normalize_name(name: str) -> str:
    name = name.strip().lower()
    name = SUFFIX_RE.sub("", name).strip()
    if name.endswith(".com"):
        name = name[:-4]
    return name


async def resolve_domain(
    company: Company, client: httpx.AsyncClient | None = None
) -> str | None:
    if company.domain:
        return company.domain

    from quarry.http import get_client

    if client is None:
        client = get_client()

    normalized = normalize_name(company.name)
    if not normalized:
        return None

    candidates = _generate_candidates(normalized)

    for domain in candidates:
        try:
            response = await client.head(f"https://{domain}", timeout=10.0)
            if response.status_code < 400:
                log.info("Resolved domain for %s: %s", company.name, domain)
                return domain
        except (httpx.RequestError, httpx.HTTPStatusError):
            continue

    log.warning("Could not resolve domain for %s", company.name)
    return None


def _generate_candidates(normalized: str) -> list[str]:
    candidates = []
    base = re.sub(r"\s+", "", normalized) + ".com"
    candidates.append(base)

    if " " in normalized:
        hyphenated = normalized.replace(" ", "-") + ".com"
        candidates.append(hyphenated)

        words = normalized.split()
        if len(words) > 1:
            first_word = words[0]
            candidates.append(first_word + ".com")

    return candidates
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_domain_resolver.py -v`
Expected: PASS

Note: The `httpx_mock` fixture requires `pytest-httpx` package. If not installed:

```bash
pip install pytest-httpx
```

- [ ] **Step 6: Commit**

```bash
git add quarry/resolve/domain_resolver.py tests/test_domain_resolver.py
git commit -m "feat: add domain resolver with guess-and-probe strategy"
```

---

### Task 5: Careers URL resolver

**Files:**
- Create: `quarry/resolve/careers_resolver.py`
- Create: `tests/test_careers_resolver.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_careers_resolver.py`:

```python
import pytest

from quarry.models import Company
from quarry.resolve.careers_resolver import resolve_careers_url


@pytest.mark.asyncio
async def test_resolve_careers_url_skip_if_already_set():
    company = Company(name="Test", careers_url="https://test.com/careers")
    client = None
    result = await resolve_careers_url(company, client)
    assert result == "https://test.com/careers"


@pytest.mark.asyncio
async def test_resolve_careers_url_skip_if_no_domain():
    company = Company(name="Test")
    result = await resolve_careers_url(company, None)
    assert result is None


@pytest.mark.asyncio
async def test_resolve_careers_url_probes_patterns(httpx_mock):
    from quarry.http import close_client, get_client

    httpx_mock.add_response(
        url="https://acme.com/careers",
        status_code=200,
        text="<html><body>View our open positions and career opportunities</body></html>",
    )
    client = get_client()
    company = Company(name="Acme", domain="acme.com")
    try:
        result = await resolve_careers_url(company, client)
        assert result is not None
        assert "/careers" in result
    finally:
        await close_client()


@pytest.mark.asyncio
async def test_resolve_careers_url_returns_redirected_url(httpx_mock):
    from quarry.http import close_client, get_client

    httpx_mock.add_response(
        url="https://acme.com/careers",
        status_code=301,
        headers={"Location": "https://acme.com/en/careers"},
    )
    httpx_mock.add_response(
        url="https://acme.com/en/careers",
        status_code=200,
        text="<html><body>Job openings and career paths</body></html>",
    )
    client = get_client()
    company = Company(name="Acme", domain="acme.com")
    try:
        result = await resolve_careers_url(company, client)
        assert result is not None
        assert "acme.com" in result
    finally:
        await close_client()


@pytest.mark.asyncio
async def test_resolve_careers_url_returns_none_if_no_pattern_works(httpx_mock):
    from quarry.http import close_client, get_client

    for pattern in ["/careers", "/jobs", "/careers/search", "/about/careers", "/en/careers"]:
        url = f"https://unknown.com{pattern}"
        httpx_mock.add_response(url=url, status_code=404)
    for pattern in ["/careers", "/jobs"]:
        url = f"https://www.unknown.com{pattern}"
        httpx_mock.add_response(url=url, status_code=404)

    client = get_client()
    company = Company(name="Unknown", domain="unknown.com")
    try:
        result = await resolve_careers_url(company, client)
        assert result is None
    finally:
        await close_client()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_careers_resolver.py -v`
Expected: FAIL

- [ ] **Step 3: Write quarry/resolve/careers_resolver.py**

Create `quarry/resolve/careers_resolver.py`:

```python
import asyncio
import logging

import httpx

from quarry.models import Company

log = logging.getLogger(__name__)

JOB_KEYWORDS = {"job", "career", "position", "opening", "apply", "opportunit"}

URL_PATTERNS = [
    "/careers",
    "/jobs",
    "/careers/search",
    "/about/careers",
    "/en/careers",
]


async def resolve_careers_url(
    company: Company, client: httpx.AsyncClient | None = None
) -> str | None:
    if company.careers_url:
        return company.careers_url

    if not company.domain:
        return None

    from quarry.http import get_client

    if client is None:
        client = get_client()

    domains = [company.domain]
    if not company.domain.startswith("www."):
        domains.append(f"www.{company.domain}")

    for domain in domains:
        for path in URL_PATTERNS:
            url = f"https://{domain}{path}"
            result = await _probe_url(client, url)
            if result:
                log.info("Resolved careers URL for %s: %s", company.name, result)
                return result

    log.warning("Could not resolve careers URL for %s", company.name)
    return None


async def _probe_url(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        response = await client.get(url, timeout=5.0)
        if response.status_code != 200:
            return None
        text = response.text.lower()
        if any(kw in text for kw in JOB_KEYWORDS):
            return str(response.url)
        return None
    except (httpx.RequestError, httpx.HTTPStatusError):
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_careers_resolver.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quarry/resolve/careers_resolver.py tests/test_careers_resolver.py
git commit -m "feat: add careers URL resolver with URL pattern probing"
```

---

### Task 6: ATS detector

**Files:**
- Create: `quarry/resolve/ats_detector.py`
- Create: `tests/test_ats_detector.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ats_detector.py`:

```python
import pytest

from quarry.resolve.ats_detector import detect_ats_url_patterns, detect_ats


def test_detect_ats_url_patterns_greenhouse():
    ats_type, slug = detect_ats_url_patterns("https://boards.greenhouse.io/takeda")
    assert ats_type == "greenhouse"
    assert slug == "takeda"


def test_detect_ats_url_patterns_greenhouse_api():
    ats_type, slug = detect_ats_url_patterns(
        "https://boards-api.greenhouse.io/v1/boards/takeda"
    )
    assert ats_type == "greenhouse"
    assert slug == "takeda"


def test_detect_ats_url_patterns_lever():
    ats_type, slug = detect_ats_url_patterns("https://jobs.lever.co/NimbleAI")
    assert ats_type == "lever"
    assert slug == "NimbleAI"


def test_detect_ats_url_patterns_ashby():
    ats_type, slug = detect_ats_url_patterns("https://jobs.ashbyhq.com/cognition")
    assert ats_type == "ashby"
    assert slug == "cognition"


def test_detect_ats_url_patterns_no_match():
    ats_type, slug = detect_ats_url_patterns("https://example.com/careers")
    assert ats_type == "unknown"
    assert slug is None


def test_detect_ats_url_patterns_no_bare_ashbyhq_domain():
    ats_type, slug = detect_ats_url_patterns("https://ashbyhq.com/careers")
    assert ats_type == "unknown"
    assert slug is None


@pytest.mark.asyncio
async def test_detect_ats_skips_known_ats():
    from quarry.http import close_client, get_client

    client = get_client()
    from quarry.models import Company

    company = Company(name="Test", ats_type="greenhouse", ats_slug="test")
    result = await detect_ats(company, client)
    assert result == ("greenhouse", "test")
    await close_client()


@pytest.mark.asyncio
async def test_detect_ats_skips_generic():
    from quarry.http import close_client, get_client

    client = get_client()
    from quarry.models import Company

    company = Company(name="Test", ats_type="generic")
    result = await detect_ats(company, client)
    assert result == ("generic", None)
    await close_client()


@pytest.mark.asyncio
async def test_detect_ats_skips_no_careers_url():
    from quarry.http import close_client, get_client

    client = get_client()
    from quarry.models import Company

    company = Company(name="Test")
    result = await detect_ats(company, client)
    assert result == ("unknown", None)
    await close_client()


@pytest.mark.asyncio
async def test_detect_ats_url_pattern_fast_path():
    from quarry.http import close_client, get_client

    client = get_client()
    from quarry.models import Company

    company = Company(
        name="Greenhouse Co", careers_url="https://boards.greenhouse.io/myco"
    )
    result = await detect_ats(company, client)
    assert result == ("greenhouse", "myco")
    await close_client()


@pytest.mark.asyncio
async def test_detect_ats_html_signature(httpx_mock):
    from quarry.http import close_client, get_client

    httpx_mock.add_response(
        url="https://example.com/careers",
        status_code=200,
        text='<html><script src="https://boards.greenhouse.io/embed.js"></script></html>',
    )
    client = get_client()
    from quarry.models import Company

    company = Company(name="Example Co", domain="example.com", careers_url="https://example.com/careers")
    result = await detect_ats(company, client)
    assert result[0] == "greenhouse"
    assert result[1] is not None
    await close_client()


@pytest.mark.asyncio
async def test_detect_ats_generic_fallback(httpx_mock):
    from quarry.http import close_client, get_client

    httpx_mock.add_response(
        url="https://example.com/careers",
        status_code=200,
        text="<html><body>Some generic careers page</body></html>",
    )
    client = get_client()
    from quarry.models import Company

    company = Company(name="Example Co", domain="example.com", careers_url="https://example.com/careers")
    result = await detect_ats(company, client)
    assert result == ("generic", None)
    await close_client()


@pytest.mark.asyncio
async def test_detect_ats_html_fetch_failure_returns_unknown(httpx_mock):
    from quarry.http import close_client, get_client

    import httpx

    httpx_mock.add_exception(httpx.ConnectTimeout("timeout"), url="https://example.com/careers")
    client = get_client()
    from quarry.models import Company

    company = Company(name="Example Co", domain="example.com", careers_url="https://example.com/careers")
    result = await detect_ats(company, client)
    assert result == ("unknown", None)
    await close_client()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ats_detector.py -v`
Expected: FAIL

- [ ] **Step 3: Write quarry/resolve/ats_detector.py**

Create `quarry/resolve/ats_detector.py`:

```python
import logging
import re
from urllib.parse import urlparse

import httpx

from quarry.models import Company

log = logging.getLogger(__name__)

ATS_URL_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(r"https?://boards\.greenhouse\.io/([^/?#]+)")),
    (
        "greenhouse",
        re.compile(r"https?://boards-api\.greenhouse\.io/v1/boards/([^/?#]+)"),
    ),
    ("lever", re.compile(r"https?://jobs\.lever\.co/([^/?#]+)")),
    ("ashby", re.compile(r"https?://jobs\.ashbyhq\.com/([^/?#]+)")),
]

HTML_SIGNATURES: dict[str, list[str]] = {
    "greenhouse": ["boards.greenhouse.io", "greenhouse.io/embed"],
    "lever": ["jobs.lever.co", "lever.co/embed"],
    "ashby": ["jobs.ashbyhq.com", "ashbyhq.com/embed"],
}


def detect_ats_url_patterns(url: str) -> tuple[str, str | None]:
    for ats_type, pattern in ATS_URL_PATTERNS:
        match = pattern.search(url)
        if match:
            return ats_type, match.group(1)
    return "unknown", None


async def detect_ats(
    company: Company, client: httpx.AsyncClient | None = None, html: str | None = None
) -> tuple[str, str | None]:
    if company.ats_type not in ("unknown",) and company.ats_type is not None:
        return company.ats_type, company.ats_slug

    if not company.careers_url:
        return "unknown", None

    ats_type, slug = detect_ats_url_patterns(company.careers_url)
    if ats_type != "unknown":
        log.info("ATS detected via URL pattern for %s: %s/%s", company.name, ats_type, slug)
        return ats_type, slug

    if html is None:
        try:
            from quarry.http import get_client

            if client is None:
                client = get_client()
            response = await client.get(company.careers_url, timeout=5.0)
            if response.status_code != 200:
                log.warning(
                    "HTML fetch failed for %s: status %d", company.name, response.status_code
                )
                return "unknown", None
            html = response.text
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            log.warning("HTML fetch error for %s: %s", company.name, e)
            return "unknown", None

    html_lower = html.lower()
    for ats_type, signatures in HTML_SIGNATURES.items():
        for sig in signatures:
            if sig in html_lower:
                slug = _extract_slug_from_html(ats_type, html, company.careers_url)
                log.info("ATS detected via HTML for %s: %s/%s", company.name, ats_type, slug)
                return ats_type, slug

    return "generic", None


def _extract_slug_from_html(
    ats_type: str, html: str, url: str
) -> str | None:
    patterns = {
        "greenhouse": re.compile(r"boards\.greenhouse\.io/([^\"'\s?#]+)"),
        "lever": re.compile(r"jobs\.lever\.co/([^\"'\s?#]+)"),
        "ashby": re.compile(r"jobs\.ashbyhq\.com/([^\"'\s?#]+)"),
    }
    pattern = patterns.get(ats_type)
    if pattern:
        match = pattern.search(html)
        if match:
            return match.group(1)
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) >= 1 and parts[0]:
        return parts[0]
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ats_detector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quarry/resolve/ats_detector.py tests/test_ats_detector.py
git commit -m "feat: add ATS detector with URL pattern and HTML signature detection"
```

---

### Task 7: Pipeline orchestrator

**Files:**
- Create: `quarry/resolve/pipeline.py`
- Create: `tests/test_resolve_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_resolve_pipeline.py`:

```python
import pytest

from quarry.models import Company
from quarry.store.db import Database, init_db


@pytest.mark.asyncio
async def test_resolve_company_skips_already_resolved():
    from quarry.resolve.pipeline import resolve_company
    from quarry.http import close_client

    company = Company(
        name="Resolved Co",
        domain="resolved.com",
        careers_url="https://resolved.com/careers",
        ats_type="greenhouse",
        ats_slug="resolved",
        resolve_status="resolved",
    )
    result = await resolve_company(company, db=None)
    assert result.resolve_status == "resolved"
    await close_client()


@pytest.mark.asyncio
async def test_resolve_company_sets_failed_after_max_attempts(httpx_mock):
    from quarry.http import close_client, get_client
    from quarry.resolve.pipeline import resolve_company

    db_path = "/tmp/test_resolve_pipeline1.db"
    import os

    if os.path.exists(db_path):
        os.remove(db_path)
    db = init_db(db_path)

    httpx_mock.add_response(url="https://failcorp.com", method="HEAD", status_code=404)

    company = Company(name="FailCorp Inc.", resolve_attempts=2)
    company.id = db.insert_company(company)
    client = get_client()

    try:
        result = await resolve_company(company, db=db, client=client)
        assert result.resolve_status == "failed"
        assert result.resolve_attempts == 3
        assert result.domain is None
    finally:
        await close_client()
        os.remove(db_path)


@pytest.mark.asyncio
async def test_resolve_unresolved_processes_unresolved_companies(httpx_mock):
    from quarry.http import close_client, get_client
    from quarry.resolve.pipeline import resolve_unresolved

    db_path = "/tmp/test_resolve_pipeline2.db"
    import os

    if os.path.exists(db_path):
        os.remove(db_path)
    db = init_db(db_path)

    httpx_mock.add_response(
        url="https://acme.com", method="HEAD", status_code=200
    )
    httpx_mock.add_response(
        url="https://acme.com/careers",
        status_code=200,
        text="<html><body>Job openings at ACME</body></html>",
    )
    httpx_mock.add_response(
        url="https://acme.com/careers",
        status_code=200,
        text="<html><body>Job openings at ACME</body></html>",
    )

    company = Company(name="Acme Inc.")
    db.insert_company(company)

    try:
        await resolve_unresolved(db)
        companies = db.get_all_companies(active_only=False)
        assert len(companies) == 1
        assert companies[0].domain == "acme.com"
    finally:
        await close_client()
        os.remove(db_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_resolve_pipeline.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Create `quarry/resolve/__init__.py`**

Create `quarry/resolve/__init__.py`:

```python
from quarry.resolve.pipeline import resolve_company, resolve_unresolved

__all__ = ["resolve_company", "resolve_unresolved"]
```

- [ ] **Step 4: Write quarry/resolve/pipeline.py**

Create `quarry/resolve/pipeline.py`:

```python
import asyncio
import logging

import httpx

from quarry.http import close_client, get_client
from quarry.models import Company
from quarry.resolve.ats_detector import detect_ats
from quarry.resolve.careers_resolver import resolve_careers_url
from quarry.resolve.domain_resolver import resolve_domain
from quarry.store.db import Database

log = logging.getLogger(__name__)

MAX_RESOLVE_ATTEMPTS = 3


async def resolve_company(
    company: Company,
    db: Database | None = None,
    client: httpx.AsyncClient | None = None,
) -> Company:
    if company.resolve_status == "resolved":
        return company

    if client is None:
        client = get_client()

    domain_changed = False
    careers_changed = False

    if not company.domain:
        domain = await resolve_domain(company, client)
        if domain:
            company.domain = domain
            company.resolve_attempts = 0
            domain_changed = True
        else:
            company.resolve_attempts += 1
            if company.resolve_attempts >= MAX_RESOLVE_ATTEMPTS:
                company.resolve_status = "failed"
                log.warning("Marking %s as failed after %d attempts", company.name, company.resolve_attempts)
            if db:
                db.update_company(company)
            return company

    if not company.careers_url and company.domain:
        careers_url = await resolve_careers_url(company, client)
        if careers_url:
            company.careers_url = careers_url
            company.resolve_attempts = 0
            careers_changed = True
        else:
            company.resolve_attempts += 1
            if company.resolve_attempts >= MAX_RESOLVE_ATTEMPTS:
                company.resolve_status = "failed"
                log.warning("Marking %s as failed after %d attempts", company.name, company.resolve_attempts)
            if db:
                db.update_company(company)
            return company

    if company.careers_url and company.ats_type == "unknown":
        ats_type, ats_slug = await detect_ats(company, client)
        company.ats_type = ats_type
        company.ats_slug = ats_slug
        if ats_type == "unknown":
            if db:
                db.update_company(company)
            return company
        company.resolve_status = "resolved"
        log.info("Resolved %s: ats_type=%s, ats_slug=%s", company.name, ats_type, ats_slug)
    elif company.careers_url and company.ats_type != "unknown":
        company.resolve_status = "resolved"

    if domain_changed or careers_changed or company.resolve_status == "resolved":
        if db:
            db.update_company(company)

    return company


async def resolve_unresolved(db: Database, client: httpx.AsyncClient | None = None) -> None:
    if client is None:
        client = get_client()

    try:
        companies = db.get_companies_by_resolve_status("unresolved")
        log.info("Resolving %d unresolved companies", len(companies))
        for company in companies:
            try:
                await resolve_company(company, db=db, client=client)
            except Exception as e:
                log.error("Error resolving %s: %s", company.name, e)
    finally:
        await close_client()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_resolve_pipeline.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add quarry/resolve/__init__.py quarry/resolve/pipeline.py tests/test_resolve_pipeline.py
git commit -m "feat: add resolve pipeline that chains domain → careers_url → ATS detection"
```

---

### Task 8: Resolve CLI command

**Files:**
- Create: `quarry/resolve/__main__.py`
- Create: `tests/test_resolve_cli.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_resolve_cli.py`:

```python
from click.testing import CliRunner

from quarry.store.db import init_db
from quarry.models import Company


def test_resolve_cli_help():
    runner = CliRunner()
    from quarry.resolve.__main__ import cli

    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "resolve" in result.output.lower() or "Resolve" in result.output


def test_resolve_cli_company_flag(tmp_path):
    db_path = tmp_path / "test_resolve_cli.db"
    db = init_db(db_path)
    company = Company(name="CLI Test Co", domain="clitest.com", careers_url="https://clitest.com/careers")
    db.insert_company(company)

    runner = CliRunner()
    from quarry.resolve.__main__ import cli

    result = runner.invoke(cli, ["--company", "CLI Test Co"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_resolve_cli.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Write quarry/resolve/__main__.py**

Create `quarry/resolve/__main__.py`:

```python
import asyncio
import logging

import click

from quarry.config import settings
from quarry.store.db import Database, init_db

log = logging.getLogger(__name__)


@click.group()
def cli():
    """Resolve company domains, careers URLs, and ATS types."""
    pass


@cli.command()
@click.option("--retry-failed", is_flag=True, help="Also retry previously failed companies")
@click.option("--company", "company_name", help="Resolve a single company by name")
@click.option("--redetect-ats", is_flag=True, help="Re-run ATS detection on generic companies")
def resolve(retry_failed: bool, company_name: str | None, redetect_ats: bool) -> None:
    """Resolve all unresolved companies (domain, careers URL, ATS type)."""
    _configure_logging()
    db = init_db(settings.db_path)

    if company_name:
        company = db.get_company_by_name(company_name)
        if not company:
            click.echo(f"Company not found: {company_name}")
            return
        click.echo(f"Resolving company: {company.name}")
        from quarry.resolve.pipeline import resolve_company

        result = asyncio.run(resolve_company(company, db=db))
        click.echo(f"Result: domain={result.domain}, careers_url={result.careers_url}, "
                    f"ats_type={result.ats_type}, status={result.resolve_status}")
        return

    if redetect_ats:
        click.echo("Re-detecting ATS types...")
        _redetect_ats(db)
        return

    from quarry.resolve.pipeline import resolve_unresolved

    click.echo("Resolving unresolved companies...")
    asyncio.run(resolve_unresolved(db))

    if retry_failed:
        click.echo("Retrying failed companies...")
        companies = db.get_companies_by_resolve_status("failed")
        for company in companies:
            company.resolve_status = "unresolved"
            company.resolve_attempts = 0
            db.update_company(company)
        asyncio.run(resolve_unresolved(db))

    unresolved = db.get_companies_by_resolve_status("unresolved")
    resolved = db.get_companies_by_resolve_status("resolved")
    failed = db.get_companies_by_resolve_status("failed")
    click.echo(f"Resolved: {len(resolved)}, Unresolved: {len(unresolved)}, Failed: {len(failed)}")


def _redetect_ats(db: Database) -> None:
    companies = db.get_all_companies(active_only=False)
    updated = 0
    for company in companies:
        if company.careers_url and company.ats_type in ("generic", "unknown"):
            company.ats_type = "unknown"
            company.ats_slug = None
            company.resolve_status = "unresolved"
            db.update_company(company)
            updated += 1
    if updated > 0:
        from quarry.resolve.pipeline import resolve_unresolved

        asyncio.run(resolve_unresolved(db))
    click.echo(f"Re-detecting ATS for {updated} companies")


def _configure_logging():
    logging.basicConfig(
        level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_resolve_cli.py -v`
Expected: PASS

- [ ] **Step 5: Run CLI manually to verify**

```bash
python -m quarry.resolve --help
python -m quarry.resolve --company "Test"
```

- [ ] **Step 6: Commit**

```bash
git add quarry/resolve/__main__.py tests/test_resolve_cli.py
git commit -m "feat: add resolve CLI with --company, --retry-failed, and --redetect-ats flags"
```

---

### Task 9: Add-company CLI command

**Files:**
- Modify: `quarry/store/__main__.py`
- Create: `tests/test_store_cli.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_store_cli.py`:

```python
from click.testing import CliRunner

from quarry.store.__main__ import cli
from quarry.store.db import init_db, Database
from quarry.models import Company


def test_add_company_basic(tmp_path):
    db_path = tmp_path / "test_store.db"
    init_db(db_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["add-company", "--name", "Test Corp"])
    assert result.exit_code == 0
    assert "Test Corp" in result.output


def test_add_company_with_domain(tmp_path):
    db_path = tmp_path / "test_store.db"
    init_db(db_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["add-company", "--name", "Test Corp", "--domain", "test.com"]
    )
    assert result.exit_code == 0

    db = Database(db_path)
    companies = db.get_all_companies(active_only=False)
    assert len(companies) == 1
    assert companies[0].domain == "test.com"


def test_add_company_with_careers_url(tmp_path):
    db_path = tmp_path / "test_store.db"
    init_db(db_path)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "add-company",
            "--name",
            "Test Corp",
            "--careers-url",
            "https://boards.greenhouse.io/testcorp",
        ],
    )
    assert result.exit_code == 0

    db = Database(db_path)
    companies = db.get_all_companies(active_only=False)
    assert len(companies) == 1
    assert companies[0].ats_type == "greenhouse"
    assert companies[0].ats_slug == "testcorp"
    assert companies[0].resolve_status == "resolved"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_store_cli.py -v`
Expected: FAIL — `add-company` command doesn't exist

- [ ] **Step 3: Add add-company command to quarry/store/__main__.py**

Update `quarry/store/__main__.py`:

```python
import asyncio

import click

from quarry.config import settings
from quarry.resolve.ats_detector import detect_ats_url_patterns
from quarry.store.db import Database, init_db
from quarry.models import Company


@click.group()
def cli():
    """Database management commands."""
    pass


@cli.command()
def init():
    """Initialize the database with schema."""
    init_db(settings.db_path)
    click.echo(f"Database initialized at {settings.db_path}")


@cli.command("add-company")
@click.option("--name", required=True, help="Company name")
@click.option("--domain", default=None, help="Company domain (e.g. example.com)")
@click.option(
    "--careers-url", default=None, help="Careers page URL (e.g. https://example.com/careers)"
)
def add_company(name: str, domain: str | None, careers_url: str | None) -> None:
    """Add a company to the database and optionally resolve its ATS type."""
    db = init_db(settings.db_path)

    existing = db.get_company_by_name(name)
    if existing:
        click.echo(f"Company already exists: {name} (id={existing.id})")
        return

    company = Company(
        name=name,
        domain=domain,
        careers_url=careers_url,
        ats_type="unknown",
        added_by="cli",
    )

    if careers_url:
        import re

        parsed = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(careers_url)
        if parsed.scheme not in ("http", "https"):
            click.echo(f"Invalid URL scheme: {careers_url}")
            return
        if not parsed.hostname:
            click.echo(f"Invalid URL: {careers_url}")
            return

        ats_type, ats_slug = detect_ats_url_patterns(careers_url)
        if ats_type != "unknown":
            company.ats_type = ats_type
            company.ats_slug = ats_slug
            company.resolve_status = "resolved"
            click.echo(f"Detected ATS: {ats_type} (slug: {ats_slug})")
        else:
            company.resolve_status = "unresolved"

    if domain and not careers_url and not company.resolve_status == "resolved":
        import re

        if not re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*\.)+[a-zA-Z]{2,}$", domain):
            click.echo(f"Invalid domain: {domain}")
            return

    company.id = db.insert_company(company)
    click.echo(f"Added company: {name} (id={company.id})")

    if company.resolve_status != "resolved" and not careers_url:
        from quarry.resolve.pipeline import resolve_company

        result = asyncio.run(resolve_company(company, db=db))
        click.echo(
            f"Resolved: domain={result.domain}, careers_url={result.careers_url}, "
            f"ats_type={result.ats_type}, status={result.resolve_status}"
        )

    from quarry.http import close_client

    asyncio.run(close_client())


if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_store_cli.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add quarry/store/__main__.py tests/test_store_cli.py
git commit -m "feat: add add-company CLI command with URL-pattern ATS detection"
```

---

### Task 10: Integrate resolve into run_once and restructure to single event loop

**Important context:** The current `run_once()` uses `asyncio.run()` per company inside `_crawl_company()`. The shared `httpx.AsyncClient` singleton from `quarry/http.py` is bound to the event loop that created it. If crawlers use `get_client()` but each `asyncio.run()` creates a new loop, the client will be invalid. The spec says: "When refactored to use the shared client, they must also run within a single event loop per batch."

This task restructures `run_once()` to use a single `asyncio.run()` that covers both the resolve phase and the crawl phase, so the shared client works correctly throughout.

**Files:**
- Modify: `quarry/agent/scheduler.py` (restructure `run_once`)
- Modify: `tests/test_scheduler.py` (update tests for new async structure)

- [ ] **Step 1: Read existing scheduler test**

Read `tests/test_scheduler.py` to understand current test mocking patterns.

- [ ] **Step 2: Write the failing test**

Add a test that verifies `resolve_unresolved` is called before the crawl loop and that the entire run uses a single event loop. Mock both `resolve_unresolved` and the crawl to verify integration order.

- [ ] **Step 3: Restructure `run_once` to use a single async entry point**

Rewrite `quarry/agent/scheduler.py`. Key changes:
1. Replace `_crawl_company` (which calls `asyncio.run()` per company) with an async version
2. Make `run_once()` call a single `asyncio.run(_async_run_once(db))` that handles both resolve and crawl
3. Move the crawl loop into the async function so all crawls share the same event loop (and thus the same `httpx.AsyncClient`)
4. Close the shared client at the end of `_async_run_once`

The new top-level `run_once()`:

```python
def run_once(db: Database) -> dict:
    """Run a single crawl cycle: resolve, crawl, process, store."""
    return asyncio.run(_async_run_once(db))


async def _async_run_once(db: Database) -> dict:
    """Async implementation of run_once. Uses a single event loop for resolve + crawl."""
    from quarry.http import close_client

    _ensure_ideal_embedding(db)
    try:
        from quarry.resolve import resolve_unresolved

        await resolve_unresolved(db)
    except Exception as e:
        log.error("Company resolution failed: %s", e)

    ideal_embedding = get_ideal_embedding(db)
    blocklist: list[str] = getattr(settings, "keyword_blocklist", []) or []

    companies = db.get_all_companies(active_only=True)
    log.info("Crawling %d active companies", len(companies))

    total_found = 0
    total_new = 0
    total_duplicates = 0
    total_filtered = 0
    companies_crawled = 0
    companies_errored = 0

    log_path = Path(
        f"crawl_log_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.csv"
    )
    log_file = open(log_path, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(log_file, fieldnames=CRAWL_LOG_COLUMNS)
    writer.writeheader()

    def _log_posting(
        raw: RawPosting, status: str, similarity: float, source: str
    ) -> None:
        writer.writerow(
            {
                "title": raw.title,
                "source": source,
                "url": raw.url,
                "location": raw.location or "",
                "similarity_score": similarity,
                "status": status,
            }
        )

    for company in companies:
        run = CrawlRun(
            company_id=company.id,
            started_at=datetime.now(timezone.utc),
            status="running",
        )

        try:
            postings = await _crawl_company_async(company)
            total_found += len(postings)
            companies_crawled += 1

            run.completed_at = datetime.now(timezone.utc)
            run.postings_found = len(postings)

            company_new = 0
            for raw in postings:
                job_posting, status, similarity = _process_posting(
                    raw, db, blocklist, ideal_embedding
                )
                _log_posting(raw, status, similarity, company.name)
                if status == "new" and job_posting:
                    db.insert_posting(job_posting)
                    company_new += 1
                    total_new += 1
                elif status.startswith("duplicate"):
                    total_duplicates += 1
                else:
                    total_filtered += 1

            run.postings_new = company_new
            run.status = "success"
        except Crawl404Error:
            log.warning("ATS 404 for %s — resetting ats_type to unknown", company.name)
            company.ats_type = "unknown"
            company.ats_slug = None
            db.update_company(company)
            companies_errored += 1
            run.status = "error"
            run.postings_found = 0
            run.postings_new = 0
        except Exception as e:
            log.error("Failed to crawl %s: %s", company.name, e)
            companies_errored += 1
            run.status = "error"
            run.postings_found = 0
            run.postings_new = 0

        db.insert_crawl_run(run)

    search_postings = _crawl_search_queries(db)
    total_found += len(search_postings)

    for raw in search_postings:
        job_posting, status, similarity = _process_posting(
            raw, db, blocklist, ideal_embedding
        )
        _log_posting(raw, status, similarity, "search")
        if status == "new" and job_posting:
            if not job_posting.company_id:
                job_posting.company_id = _resolve_company_id(raw, db)
            db.insert_posting(job_posting)
            total_new += 1
        elif status.startswith("duplicate"):
            total_duplicates += 1
        else:
            total_filtered += 1

    log_file.close()

    summary = {
        "companies_crawled": companies_crawled,
        "companies_errored": companies_errored,
        "total_found": total_found,
        "total_new": total_new,
        "total_duplicates": total_duplicates,
        "total_filtered": total_filtered,
        "crawl_log": str(log_path),
    }
    log.info("Run complete: %s", summary)

    await close_client()
    return summary


async def _crawl_company_async(company: Company) -> list[RawPosting]:
    """Crawl a single company's job postings (async version using shared client)."""
    crawler = get_crawler(company)
    return await crawler.crawl(company)
```

Remove the old `_crawl_company` function (the sync wrapper that used `asyncio.run()`).

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: PASS (may need to update mocking patterns since `_crawl_company` is now `_crawl_company_async`)

- [ ] **Step 5: Commit**

```bash
git add quarry/agent/scheduler.py tests/test_scheduler.py
git commit -m "feat: integrate resolve into run_once, restructure to single async event loop"
```

---

### Task 11: Refactor crawlers to use shared HTTP client

**Prerequisite:** Task 10 must be completed first — it restructures `run_once()` to use a single event loop so the shared `httpx.AsyncClient` works correctly across all crawls.

**Files:**
- Modify: `quarry/crawlers/greenhouse.py`
- Modify: `quarry/crawlers/lever.py`
- Modify: `quarry/crawlers/ashby.py`
- Modify: `quarry/crawlers/careers_page.py`

For each crawler, the pattern is the same:
1. Add `from quarry.http import get_client` to imports
2. Keep `import httpx` for exception types (`httpx.HTTPStatusError`, `httpx.RequestError`)
3. Replace `async with httpx.AsyncClient(timeout=10.0) as client:` with `client = get_client()`
4. Remove the `async with` context manager — the shared client stays open for the lifetime of the event loop

- [ ] **Step 1: Modify greenhouse.py**

In `quarry/crawlers/greenhouse.py`:
- Add `from quarry.http import get_client` to imports (keep `import httpx`)
- In `crawl()` method, replace:
  ```python
  async with httpx.AsyncClient(timeout=10.0) as client:
      try:
          response = await client.get(url)
          ...
  ```
  With:
  ```python
  client = get_client()
  try:
      response = await client.get(url)
      ...
  ```
  (Remove one level of indentation for the try/except block)

- [ ] **Step 2: Modify lever.py**

Same pattern in `quarry/crawlers/lever.py`.
- Add `from quarry.http import get_client`
- Replace `async with httpx.AsyncClient(timeout=10.0) as client:` with `client = get_client()`
- Remove one level of indentation from the try/except block

- [ ] **Step 3: Modify ashby.py**

Same pattern in `quarry/crawlers/ashby.py`.
- Add `from quarry.http import get_client`
- Replace `async with httpx.AsyncClient(timeout=10.0) as client:` with `client = get_client()`
- Remove one level of indentation

- [ ] **Step 4: Modify careers_page.py**

In `quarry/crawlers/careers_page.py`:
- Add `from quarry.http import get_client` to imports
- In `_fetch_page()`, replace:
  ```python
  async with httpx.AsyncClient(
      timeout=10.0,
      follow_redirects=True,
      limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
  ) as client:
      async with client.stream("GET", url) as response:
  ```
  With:
  ```python
  client = get_client()
  async with client.stream("GET", url) as response:
  ```
  The shared client already has `follow_redirects=True` and connection limits configured.

- [ ] **Step 5: Run all crawler tests**

Run: `python -m pytest tests/test_greenhouse_crawler.py tests/test_lever_crawler.py tests/test_ashby_crawler.py tests/test_careers_page_crawler.py -v`
Expected: All pass

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest -v`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add quarry/crawlers/greenhouse.py quarry/crawlers/lever.py quarry/crawlers/ashby.py quarry/crawlers/careers_page.py
git commit -m "refactor: crawlers use shared httpx.AsyncClient singleton from quarry/http.py"
```

---

### Task 12: End-to-end integration test

**Files:**
- Create: `tests/test_resolve_e2e.py`

- [ ] **Step 1: Write end-to-end test**

Create `tests/test_resolve_e2e.py`:

```python
import sqlite3

import pytest

from quarry.models import Company
from quarry.store.db import Database, init_db


def test_full_resolve_pipeline_e2e(tmp_path):
    db = init_db(tmp_path / "test_e2e.db")

    company = Company(name="Greenhouse Test Corp")
    company.id = db.insert_company(company)
    assert company.id is not None

    fetched = db.get_company(company.id)
    assert fetched is not None
    assert fetched.resolve_status == "unresolved"
    assert fetched.resolve_attempts == 0

    company.domain = "example.com"
    company.careers_url = "https://boards.greenhouse.io/examplecorp"
    company.ats_type = "greenhouse"
    company.ats_slug = "examplecorp"
    company.resolve_status = "resolved"
    db.update_company(company)

    fetched = db.get_company(company.id)
    assert fetched.resolve_status == "resolved"
    assert fetched.ats_type == "greenhouse"


def test_migrate_existing_resolved_companies(tmp_path):
    db_path = tmp_path / "test_migrate.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE companies (id INTEGER PRIMARY KEY, name TEXT, domain TEXT, "
        "careers_url TEXT, ats_type TEXT DEFAULT 'unknown', ats_slug TEXT, "
        "active BOOLEAN DEFAULT TRUE, crawl_priority INTEGER DEFAULT 5, "
        "notes TEXT, added_by TEXT DEFAULT 'seed', added_reason TEXT, "
        "last_crawled_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO companies (name, domain, careers_url, ats_type, ats_slug) "
        "VALUES ('Resolved Corp', 'resolved.com', 'https://resolved.com/careers', 'greenhouse', 'resolved')"
    )
    conn.execute(
        "INSERT INTO companies (name, ats_type) VALUES ('Unknown Corp', 'unknown')"
    )
    conn.commit()
    conn.close()

    db = Database(db_path)
    db.migrate_resolve_columns()

    resolved = db.get_company_by_name("Resolved Corp")
    assert resolved is not None
    assert resolved.resolve_status == "resolved"

    unknown = db.get_company_by_name("Unknown Corp")
    assert unknown is not None
    assert unknown.resolve_status == "unresolved"
```

- [ ] **Step 2: Run the e2e tests**

Run: `python -m pytest tests/test_resolve_e2e.py -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest -v`
Expected: All tests pass

- [ ] **Step 4: Run type checker**

Run: `PYTHONPATH=/home/kurtt/job-search pyright quarry/`
Expected: No new errors related to resolve package

- [ ] **Step 5: Run linter**

Run: `ruff check quarry/`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add tests/test_resolve_e2e.py
git commit -m "test: add end-to-end integration tests for company resolver pipeline"
```