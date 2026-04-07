# M1: Project Scaffolding and Database Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create repo layout, config loading, SQLite schema, and basic database operations.

**Architecture:** Create the directory structure per README.md, implement config loading from YAML + env overrides, create SQLite schema with all tables, and implement basic CRUD helpers.

**Tech Stack:** Python, SQLite, PyYAML, python-dotenv, Pydantic

---

## File Structure

```
quarry/
├── config.py                  # Config dataclass with YAML + env loading
├── config.yaml.example        # Example config with all fields documented
├── requirements.txt           # Dependencies
├── store/
│   ├── __init__.py
│   ├── db.py                  # Connection helper, init(), CRUD helpers
│   └── schema.sql             # Full schema definition
└── models.py                  # Pydantic models (Company, JobPosting, etc.)
```

---

### Task 1: Create Repository Structure

**Files:**
- Create: `quarry/requirements.txt`
- Create: `quarry/__init__.py`
- Create: `quarry/store/__init__.py`

- [ ] **Step 1: Create requirements.txt**

```txt
# Core
boto3>=1.34.0                # AWS SDK for Bedrock
requests>=2.31.0
apscheduler>=3.10.0
flask>=3.0.0
tenacity>=8.2.0
pyyaml>=6.0

# Embedding + ML
sentence-transformers>=2.7.0
scikit-learn>=1.4.0
numpy>=1.26.0

# Crawling
httpx>=0.27.0
beautifulsoup4>=4.12.0
python-jobspy>=1.1.0

# Utils
python-dotenv>=1.0.0
click>=8.1.0
pandas>=2.0.0
pydantic>=2.0.0
pydantic-settings>=2.0.0

# Dev
pytest>=8.0.0
```

- [ ] **Step 2: Create __init__.py files**

```python
# quarry/__init__.py
"""Quarry — Agentic Job Search System"""
__version__ = "0.1.0"
```

```python
# quarry/store/__init__.py
"""Database storage layer"""
```

- [ ] **Step 3: Create empty placeholder files for all modules**

```python
# quarry/config.py
# Placeholder - will be implemented in Task 2
```

```python
# quarry/models.py
# Placeholder - will be implemented in Task 3
```

```python
# quarry/store/db.py
# Placeholder - will be implemented in Task 4
```

- [ ] **Step 4: Create tests directory**

```bash
mkdir -p tests
touch tests/__init__.py
```

- [ ] **Step 5: Commit**

```bash
git add quarry/ tests/
git commit -m "chore: create repository structure"
```

---

### Task 2: Config Loading

**Files:**
- Modify: `quarry/config.py`
- Create: `quarry/config.yaml.example`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
import pytest
import os
from pathlib import Path

os.environ["ANTHROPIC_API_KEY"] = "test-key"

from quarry.config import Settings, load_config

def test_settings_defaults():
    settings = Settings()
    assert settings.db_path == "quarry.db"
    assert settings.similarity_threshold == 0.35

def test_load_config_from_yaml(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
db_path: test.db
similarity_threshold: 0.5
""")
    settings = load_config(config_file)
    assert settings.db_path == "test.db"
    assert settings.similarity_threshold == 0.5
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/kurtt/job-search/quarry
PYTHONPATH=/home/kurtt/job-search/quarry python -m pytest /home/kurtt/job-search/tests/test_config.py -v
```
Expected: FAIL (Settings class incomplete)

- [ ] **Step 3: Implement config.py**

```python
# quarry/config.py
from pathlib import Path
from typing import Literal

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Env vars have highest priority, then init kwargs (from YAML)
        # Note: pydantic-settings v2 applies init kwargs before env by default.
        # We handle this by only passing yaml values as defaults, not override.
    )

    # Core
    db_path: str = "quarry.db"
    seed_file: str = "seed_data.yaml"

    # Role targeting
    ideal_role_description: str = ""
    similarity_threshold: float = 0.35
    dedup_window_days: int = 90

    # Crawling
    crawl_hour: int = 8
    crawl_schedule_cron: str = "0 7 * * *"
    careers_crawl_cron: str = "0 8 * * 1"
    reflection_after_crawl: bool = True

    # Notifications
    digest_time: str = "08:30"

    # LLM (via OpenRouter or Bedrock)
    llm_provider: Literal["bedrock", "openrouter"] = "bedrock"
    # For Bedrock:
    aws_region: str = "us-east-1"
    aws_profile: str | None = None
    # For OpenRouter:
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-3-sonnet"
    max_reflection_tokens: int = 2048

    # Embeddings
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_provider: Literal["local", "openai"] = "local"
    openai_api_key: str = ""

    # Classifier
    retrain_label_threshold: int = 20
    model_dir: str = "./models/"

    # User profile for enrichment
    user_profile: str = ""

    # Digest
    digest_top_n: int = 20


def load_config(config_path: Path | None = None) -> Settings:
    """Load config from YAML file, with env var overrides.
    
    Priority (highest to lowest): env vars > YAML > defaults
    """
    import os
    
    if config_path is None:
        config_path = Path("config.yaml")

    yaml_config = {}
    if config_path.exists():
        with open(config_path) as f:
            yaml_config = yaml.safe_load(f) or {}

    # Build override dict from env vars - these always win
    env_overrides = {}
    for field_name, field_info in Settings.model_fields.items():
        env_key = field_name.upper()
        if env_key in os.environ:
            env_val = os.environ[env_key]
            # Parse to correct type if needed
            anno = field_info.annotation
            if anno in (int, float, bool, str):
                env_overrides[field_name] = anno(env_val)
            elif getattr(anno, '__origin__', None) is list:
                env_overrides[field_name] = [x.strip() for x in env_val.split(',')]
            else:
                env_overrides[field_name] = env_val
    
    # Merge: YAML values, then env overrides (which take precedence)
    combined = {**yaml_config, **env_overrides}
    return Settings(**combined)


settings = load_config()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/kurtt/job-search/quarry
PYTHONPATH=/home/kurtt/job-search/quarry python -m pytest /home/kurtt/job-search/tests/test_config.py -v
```
Expected: PASS

- [ ] **Step 5: Create config.yaml.example**

```yaml
# === Core ===
db_path: ./quarry.db
seed_file: ./seed_data.yaml

# === Role targeting ===
ideal_role_description: |
  Senior People Analytics or HR Technology leader role at a growth-stage
  tech company. Ideally involves building or leading a function, not just
  executing. Strong preference for companies doing interesting technical work.
  Open to Principal IC or Senior Manager scope.

keyword_blocklist:
  - "staffing agency"
  - "requires clearance"
  - "relocation required"

similarity_threshold: 0.58
dedup_window_days: 90

# === Crawling ===
crawl_hour: 8
crawl_schedule_cron: "0 7 * * *"
careers_crawl_cron: "0 8 * * 1"
reflection_after_crawl: true

# === Notifications ===
digest_time: "08:30"

# === LLM (Bedrock or OpenRouter) ===
llm_provider: bedrock  # "bedrock" or "openrouter"
aws_region: us-east-1
# aws_profile: default  # optional, for named profile
# openrouter_api_key: ""  # Set via OPENROUTER_API_KEY env var
# openrouter_model: anthropic/claude-3-sonnet
max_reflection_tokens: 2048

# === Embeddings ===
embedding_model: all-MiniLM-L6-v2
# embedding_provider: openai  # Uncomment to use OpenAI
# openai_api_key: ""

# User profile for LLM enrichment
user_profile: |
  Describe your background, target roles, and dealbreakers here.

# === Digest ===
digest_top_n: 20
```

- [ ] **Step 6: Commit**

```bash
git add quarry/config.py quarry/config.yaml.example tests/test_config.py
git commit -m "feat: add config loading from YAML with env overrides"
```

---

### Task 3: Pydantic Models

**Files:**
- Create: `quarry/models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_models.py`:

```python
import pytest
from datetime import datetime
from quarry.models import Company, RawPosting, JobPosting, Label, CrawlRun

def test_company_defaults():
    company = Company(name="Test Corp")
    assert company.name == "Test Corp"
    assert company.ats_type == "unknown"
    assert company.active is True

def test_raw_posting_required_fields():
    posting = RawPosting(
        company_id=1,
        title="Software Engineer",
        url="https://example.com/job",
        source_type="greenhouse"
    )
    assert posting.title == "Software Engineer"

def test_job_posting_status_default():
    posting = JobPosting(
        company_id=1,
        title="Engineer",
        url="https://example.com",
        title_hash="abc",
        status="new"
    )
    assert posting.status == "new"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/kurtt/job-search/quarry
PYTHONPATH=/home/kurtt/job-search/quarry python -m pytest /home/kurtt/job-search/tests/test_models.py -v
```
Expected: FAIL (models module incomplete)

- [ ] **Step 3: Implement models.py**

```python
# quarry/models.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Company(BaseModel):
    id: int | None = None
    name: str
    domain: str | None = None
    careers_url: str | None = None
    ats_type: Literal["greenhouse", "lever", "ashby", "generic", "unknown"] = "unknown"
    ats_slug: str | None = None
    active: bool = True
    crawl_priority: int = 5
    notes: str | None = None
    added_by: str = "seed"
    added_reason: str | None = None
    last_crawled_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RawPosting(BaseModel):
    company_id: int
    title: str
    url: str
    description: str | None = None
    location: str | None = None
    remote: bool | None = None
    posted_at: datetime | None = None
    source_id: str | None = None
    source_type: str


class JobPosting(BaseModel):
    id: int | None = None
    company_id: int
    title: str
    title_hash: str
    url: str
    description: str | None = None
    location: str | None = None
    remote: bool | None = None
    posted_at: datetime | None = None
    source_id: str | None = None
    source_type: str | None = None

    # Filtering scores
    similarity_score: float | None = None
    classifier_score: float | None = None
    embedding: bytes | None = None

    # Enrichment
    fit_score: int | None = None
    role_tier: Literal["reach", "match", "strong_match"] | None = None
    fit_reason: str | None = None
    key_requirements: str | None = None
    enriched_at: datetime | None = None

    # Lifecycle
    status: Literal["new", "seen", "applied", "rejected", "archived"] = "new"
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


class Label(BaseModel):
    id: int | None = None
    posting_id: int
    signal: Literal["positive", "negative", "applied", "skip"]
    notes: str | None = None
    labeled_at: datetime | None = None
    label_source: Literal["user", "inferred"] = "user"


class CrawlRun(BaseModel):
    id: int | None = None
    company_id: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: Literal["success", "error", "partial"] | None = None
    postings_found: int = 0
    postings_new: int = 0
    error_message: str | None = None


class SearchQuery(BaseModel):
    id: int | None = None
    query_text: str
    site: str | None = None
    active: bool = True
    added_by: str = "user"
    added_reason: str | None = None
    retired_reason: str | None = None
    postings_found: int = 0
    positive_labels: int = 0
    created_at: datetime | None = None


class ClassifierVersion(BaseModel):
    id: int | None = None
    trained_at: datetime | None = None
    training_samples: int = 0
    positive_samples: int = 0
    negative_samples: int = 0
    cv_accuracy: float | None = None
    cv_precision: float | None = None
    cv_recall: float | None = None
    model_path: str | None = None
    active: bool = False
    notes: str | None = None


class AgentAction(BaseModel):
    id: int | None = None
    run_id: str | None = None
    tool_name: str
    tool_args: str | None = None
    tool_result: str | None = None
    rationale: str | None = None
    created_at: datetime | None = None


class FilterResult(BaseModel):
    posting: RawPosting
    passed: bool
    skip_reason: Literal["duplicate", "blocklist", "low_similarity"] | None = None
    similarity_score: float | None = None


class EnrichedPosting(BaseModel):
    posting_id: int
    fit_score: int
    role_tier: Literal["reach", "match", "strong_match"]
    fit_reason: str
    key_requirements: list[str]


class DigestEntry(BaseModel):
    company_name: str
    title: str
    url: str
    role_tier: str
    fit_score: int
    similarity_score: float
    fit_reason: str
    location: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/kurtt/job-search/quarry
PYTHONPATH=/home/kurtt/job-search/quarry python -m pytest /home/kurtt/job-search/tests/test_models.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quarry/models.py tests/test_models.py
git commit -m "feat: add Pydantic models for all entities"
```

---

### Task 4: Database Schema and CRUD

**Files:**
- Create: `quarry/store/schema.py`
- Modify: `quarry/store/db.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_db.py`:

```python
import pytest
import sqlite3
from pathlib import Path
from quarry.store.db import Database, init_db, get_db

def test_init_creates_tables(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check tables exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    
    assert "companies" in tables
    assert "job_postings" in tables
    assert "labels" in tables
    assert "crawl_runs" in tables
    assert "search_queries" in tables
    assert "classifier_versions" in tables
    assert "agent_actions" in tables
    
    conn.close()

def test_db_context_manager(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)  # Initialize schema first
    db = Database(db_path)
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM companies")
        count = cursor.fetchone()[0]
        assert count == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/kurtt/job-search/quarry
PYTHONPATH=/home/kurtt/job-search/quarry python -m pytest /home/kurtt/job-search/tests/test_db.py -v
```
Expected: FAIL (db module incomplete)

- [ ] **Step 3: Create schema.py**

```python
# quarry/store/schema.py
"""Database schema SQL - embedded for easier distribution"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS companies (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    domain          TEXT,
    careers_url     TEXT,
    ats_type        TEXT DEFAULT 'unknown',
    ats_slug        TEXT,
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
    remote          BOOLEAN,
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

- [ ] **Step 4: Implement db.py**

```python
# quarry/store/db.py
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import quarry.models as models
from quarry.store.schema import SCHEMA_SQL


class Database:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self.get_connection() as conn:
            cursor = conn.execute(sql, params)
            return cursor.fetchall()

    def executemany(self, sql: str, params: list[tuple]) -> int:
        with self.get_connection() as conn:
            cursor = conn.executemany(sql, params)
            return cursor.rowcount

    # Company CRUD
    def insert_company(self, company: models.Company) -> int:
        sql = """
            INSERT INTO companies (name, domain, careers_url, ats_type, ats_slug,
                active, crawl_priority, notes, added_by, added_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            cursor = conn.execute(sql, (
                company.name, company.domain, company.careers_url,
                company.ats_type, company.ats_slug, company.active,
                company.crawl_priority, company.notes, company.added_by,
                company.added_reason
            ))
            return cursor.lastrowid

    def get_company(self, company_id: int) -> models.Company | None:
        sql = "SELECT * FROM companies WHERE id = ?"
        rows = self.execute(sql, (company_id,))
        if rows:
            return models.Company(**dict(rows[0]))
        return None

    def get_all_companies(self, active_only: bool = True) -> list[models.Company]:
        sql = "SELECT * FROM companies"
        if active_only:
            sql += " WHERE active = 1"
        rows = self.execute(sql)
        return [models.Company(**dict(row)) for row in rows]

    def update_company(self, company: models.Company) -> None:
        sql = """
            UPDATE companies SET name=?, domain=?, careers_url=?, ats_type=?,
                ats_slug=?, active=?, crawl_priority=?, notes=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """
        self.execute(sql, (
            company.name, company.domain, company.careers_url,
            company.ats_type, company.ats_slug, company.active,
            company.crawl_priority, company.notes, company.id
        ))

    # JobPosting CRUD
    def insert_posting(self, posting: models.JobPosting) -> int:
        sql = """
            INSERT INTO job_postings (company_id, title, title_hash, url, description,
                location, remote, posted_at, source_id, source_type, similarity_score,
                classifier_score, embedding, fit_score, role_tier, fit_reason,
                key_requirements, enriched_at, status, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            cursor = conn.execute(sql, (
                posting.company_id, posting.title, posting.title_hash, posting.url,
                posting.description, posting.location, posting.remote, posting.posted_at,
                posting.source_id, posting.source_type, posting.similarity_score,
                posting.classifier_score, posting.embedding, posting.fit_score,
                posting.role_tier, posting.fit_reason, posting.key_requirements,
                posting.enriched_at, posting.status, posting.first_seen_at,
                posting.last_seen_at
            ))
            return cursor.lastrowid

    def posting_exists(self, company_id: int, title_hash: str) -> bool:
        sql = "SELECT 1 FROM job_postings WHERE company_id = ? AND title_hash = ?"
        rows = self.execute(sql, (company_id, title_hash))
        return len(rows) > 0

    def get_postings(self, status: str | None = None, limit: int = 100) -> list[models.JobPosting]:
        sql = "SELECT * FROM job_postings"
        params = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " LIMIT ?"
        params = params + (limit,)
        rows = self.execute(sql, params)
        return [models.JobPosting(**dict(row)) for row in rows]

    # Label CRUD
    def insert_label(self, label: models.Label) -> int:
        sql = """
            INSERT INTO labels (posting_id, signal, notes, labeled_at, label_source)
            VALUES (?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            cursor = conn.execute(sql, (
                label.posting_id, label.signal, label.notes,
                label.labeled_at, label.label_source
            ))
            return cursor.lastrowid

    # CrawlRun CRUD
    def insert_crawl_run(self, run: models.CrawlRun) -> int:
        sql = """
            INSERT INTO crawl_runs (company_id, started_at, completed_at, status,
                postings_found, postings_new, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            cursor = conn.execute(sql, (
                run.company_id, run.started_at, run.completed_at, run.status,
                run.postings_found, run.postings_new, run.error_message
            ))
            return cursor.lastrowid

    # SearchQuery CRUD
    def insert_search_query(self, query: models.SearchQuery) -> int:
        sql = """
            INSERT INTO search_queries (query_text, site, active, added_by,
                added_reason, postings_found, positive_labels)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            cursor = conn.execute(sql, (
                query.query_text, query.site, query.active, query.added_by,
                query.added_reason, query.postings_found, query.positive_labels
            ))
            return cursor.lastrowid

    def get_active_search_queries(self) -> list[models.SearchQuery]:
        sql = "SELECT * FROM search_queries WHERE active = 1"
        rows = self.execute(sql)
        return [models.SearchQuery(**dict(row)) for row in rows]

    # AgentAction CRUD
    def insert_agent_action(self, action: models.AgentAction) -> int:
        sql = """
            INSERT INTO agent_actions (run_id, tool_name, tool_args, tool_result, rationale)
            VALUES (?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            cursor = conn.execute(sql, (
                action.run_id, action.tool_name, action.tool_args,
                action.tool_result, action.rationale
            ))
            return cursor.lastrowid

    # Settings
    def get_setting(self, key: str) -> str | None:
        sql = "SELECT value FROM settings WHERE key = ?"
        rows = self.execute(sql, (key,))
        return rows[0]["value"] if rows else None

    def set_setting(self, key: str, value: str) -> None:
        sql = """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
        """
        self.execute(sql, (key, value, value))


def init_db(db_path: str | Path) -> Database:
    """Initialize database with schema."""
    db_path = Path(db_path)
    db = Database(db_path)
    
    with db.get_connection() as conn:
        conn.executescript(SCHEMA_SQL)
    
    return db


def get_db() -> Database:
    """Get database instance from config."""
    from quarry.config import settings
    return Database(settings.db_path)
```

- [ ] **Step 6: Run test to verify it passes**

```bash
cd /home/kurtt/job-search/quarry
PYTHONPATH=/home/kurtt/job-search/quarry python -m pytest /home/kurtt/job-search/tests/test_db.py -v
```
Expected: PASS

- [ ] **Step 7: Add CLI entrypoint**

Create `quarry/store/__main__.py`:

```python
# quarry/store/__main__.py
import click
from quarry.store.db import init_db
from quarry.config import settings


@click.group()
def cli():
    """Database management commands."""
    pass


@cli.command()
def init():
    """Initialize the database with schema."""
    init_db(settings.db_path)
    click.echo(f"Database initialized at {settings.db_path}")


if __name__ == "__main__":
    cli()
```

- [ ] **Step 8: Commit**

```bash
git add quarry/store/ tests/test_db.py
git commit -m "feat: add database schema and CRUD operations"
```

---

## Acceptance Criteria

1. `python -m quarry.store init` creates a valid SQLite file with all tables
2. Config loading works from YAML with env var overrides (env vars take precedence)
3. All Pydantic models are defined and validated
4. Basic CRUD operations work for companies, postings, labels

**Note:** Dedup strategy (title_hash vs source_id) deferred until job search results can be evaluated. Schema uses simple title_hash for now; can add source_id-based dedup in pipeline later.

---

**Status:** Refined

## Plan Complete

**Plan saved to:** `docs/superpowers/plans/2026-04-05-m1-project-scaffolding.md`