# Quarry — Architecture & Data Models

## System Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    APScheduler (daily)                       │
└───────────────────────────┬─────────────────────────────────┘
                            │ triggers
┌───────────────────────────▼─────────────────────────────────┐
│                    Crawl Run (two paths)                      │
│   Broad discovery: JobSpy → Indeed/Glassdoor/Google/ZipRec   │
│   Watchlist:       CrawlerRouter → [GH|Lever|Ashby|Generic]  │
│   Output: list[RawPosting]                                   │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                  Filtering Pipeline                           │
│   1. Dedup (title_hash + company_id, 90-day window)          │
│   2. Keyword blocklist                                        │
│   3. Embed posting → cosine_sim vs. target_role_vector       │
│   4. [Phase 2] Classifier score                              │
│   Output: list[FilteredPosting] (similarity_score attached)  │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                  Enrichment Agent (Claude)                    │
│   Single-turn, batched                                        │
│   Input: list[FilteredPosting]                               │
│   Output: list[EnrichedPosting] with fit_score, tier, reason │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                     SQLite Store                              │
│   Tables: companies, job_postings, labels, crawl_runs,       │
│           search_queries, classifier_versions, agent_actions  │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                   Digest / Notification                       │
│   stdout + optional Slack webhook                            │
│   Grouped by tier: strong_match > match > reach              │
└─────────────────────────────────────────────────────────────┘
```

---

## Database Schema

### `companies`
```sql
CREATE TABLE companies (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    domain          TEXT,
    careers_url     TEXT,
    ats_type        TEXT,       -- "greenhouse" | "lever" | "ashby" | "generic" | "unknown"
    ats_slug        TEXT,       -- slug used in ATS API URLs
    active          BOOLEAN DEFAULT TRUE,
    crawl_priority  INTEGER DEFAULT 5,   -- 1 (low) to 10 (high)
    notes           TEXT,               -- agent-written notes
    added_by        TEXT DEFAULT 'seed', -- "seed" | "agent" | "user"
    added_reason    TEXT,
    last_crawled_at TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### `job_postings`
```sql
CREATE TABLE job_postings (
    id              INTEGER PRIMARY KEY,
    company_id      INTEGER REFERENCES companies(id),
    title           TEXT NOT NULL,
    title_hash      TEXT NOT NULL,       -- sha256(lower(title))
    url             TEXT NOT NULL,
    description     TEXT,
    location        TEXT,
    remote          BOOLEAN,
    posted_at       TIMESTAMP,
    source_id       TEXT,               -- ATS-native job ID
    source_type     TEXT,

    -- Filtering scores
    similarity_score    REAL,
    classifier_score    REAL,           -- [Phase 2]
    embedding           BLOB,           -- serialized numpy array

    -- Enrichment (from LLM)
    fit_score           INTEGER,        -- 1-5
    role_tier           TEXT,           -- "reach" | "match" | "strong_match"
    fit_reason          TEXT,
    key_requirements    TEXT,           -- JSON array of strings
    enriched_at         TIMESTAMP,

    -- Lifecycle
    status          TEXT DEFAULT 'new', -- "new" | "seen" | "applied" | "rejected" | "archived"
    first_seen_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(company_id, title_hash)
);

CREATE INDEX idx_postings_company ON job_postings(company_id);
CREATE INDEX idx_postings_status ON job_postings(status);
CREATE INDEX idx_postings_tier ON job_postings(role_tier);
```

### `labels`
```sql
CREATE TABLE labels (
    id          INTEGER PRIMARY KEY,
    posting_id  INTEGER REFERENCES job_postings(id),
    signal      TEXT NOT NULL,   -- "positive" | "negative" | "applied" | "skip"
    notes       TEXT,
    labeled_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    label_source TEXT DEFAULT 'user'  -- "user" | "inferred"
);
```

### `crawl_runs`
```sql
CREATE TABLE crawl_runs (
    id              INTEGER PRIMARY KEY,
    company_id      INTEGER REFERENCES companies(id),
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    status          TEXT,        -- "success" | "error" | "partial"
    postings_found  INTEGER DEFAULT 0,
    postings_new    INTEGER DEFAULT 0,
    error_message   TEXT
);
```

### `search_queries` (Phase 2)
```sql
CREATE TABLE search_queries (
    id              INTEGER PRIMARY KEY,
    query_text      TEXT NOT NULL,
    site            TEXT,        -- "indeed" | null (general)
    active          BOOLEAN DEFAULT TRUE,
    added_by        TEXT DEFAULT 'user',
    added_reason    TEXT,
    retired_reason  TEXT,
    postings_found  INTEGER DEFAULT 0,
    positive_labels INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### `classifier_versions` (Phase 2)
```sql
CREATE TABLE classifier_versions (
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
```

### `agent_actions` (Phase 2)
```sql
CREATE TABLE agent_actions (
    id          INTEGER PRIMARY KEY,
    run_id      TEXT,            -- uuid for the agent run
    tool_name   TEXT NOT NULL,
    tool_args   TEXT,            -- JSON
    tool_result TEXT,            -- JSON
    rationale   TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Pydantic Models

```python
# models.py

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

class FilterResult(BaseModel):
    posting: RawPosting
    passed: bool
    skip_reason: str | None = None   # "duplicate" | "blocklist" | "low_similarity"
    similarity_score: float | None = None

class EnrichedPosting(BaseModel):
    posting_id: int
    fit_score: int                   # 1-5
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
    location: str | None
```

---

## Configuration

```python
# config.py — via pydantic-settings

class Settings(BaseSettings):
    # Anthropic
    anthropic_api_key: str
    claude_model: str = "claude-opus-4-5"

    # Embeddings
    embedding_model: str = "all-MiniLM-L6-v2"
    target_role_description: str   # Your ideal role — used as embedding reference vector

    # User profile for LLM enrichment (separate from embedding target)
    user_profile: str              # 1-3 paragraph description of background, targets, dealbreakers

    # Filtering
    keyword_blocklist: list[str] = ["intern", "director of", "vp of", "chief", "student"]
    similarity_threshold: float = 0.35
    dedup_window_days: int = 90

    # Digest
    digest_top_n: int = 20
    slack_webhook_url: str | None = None

    # Scheduler
    crawl_hour: int = 8            # local hour for daily crawl

    # Paths
    db_path: str = "jobhound.db"
    models_dir: str = "models/"

    class Config:
        env_file = ".env"
```

---

## Crawlers

Two distinct crawling strategies serve different purposes.

### Broad Discovery — JobSpy (`python-jobspy`)

Use `python-jobspy` for keyword-based search across major job boards. Returns structured `JobPost` objects with no HTML parsing needed — title, company, URL, description, location, remote flag, salary, and date posted are all extracted automatically.

```python
from jobspy import scrape_jobs

jobs = scrape_jobs(
    site_name=["indeed", "glassdoor", "google", "zip_recruiter"],
    search_term="people analytics director",
    location="San Francisco",
    results_wanted=50,
    hours_old=48,
    is_remote=True,
)
# Returns a pandas DataFrame; convert rows to RawPosting for the pipeline
```

| Source | Reliability | Notes |
|---|---|---|
| Indeed | ★★★★★ | Best source; minimal rate limiting |
| Google Jobs | ★★★★☆ | Good breadth; requires specific query syntax |
| Glassdoor | ★★★★☆ | Good coverage |
| ZipRecruiter | ★★★☆☆ | US/Canada only |
| LinkedIn | ★★☆☆☆ | Rate-limits at ~10th page; proxies needed; not a primary source |

**Note:** There is also a community `jobspy-mcp-server` that wraps JobSpy as an MCP tool. Worth evaluating — if adopted, it would let the agent issue job searches as direct tool calls with no wrapper code needed in this repo.

### Company Watchlist — ATS Endpoint Crawlers

Direct crawling of specific companies' ATS endpoints. Highest signal, lowest noise, not covered by JobSpy. Used for the company watchlist use case where you want reliable tracking of specific employers.

```python
class BaseCrawler(ABC):
    @abstractmethod
    async def crawl(self, company: Company) -> list[RawPosting]:
        pass

class GreenhouseCrawler(BaseCrawler):
    # GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
    # Public JSON API, no auth. Returns structured job data with full description HTML.

class LeverCrawler(BaseCrawler):
    # GET https://api.lever.co/v0/postings/{slug}?mode=json
    # Public JSON API, no auth.

class AshbyCrawler(BaseCrawler):
    # POST https://jobs.ashbyhq.com/api/non-user-graphql
    # GraphQL endpoint used by Ashby job boards. No auth required.
    # Query: jobBoard(organizationHostedJobsPageName: "{slug}")

class GenericCrawler(BaseCrawler):
    # httpx GET + BeautifulSoup fallback.
    # Less reliable — postings from this source should be flagged for review.

class CrawlerRouter:
    def get_crawler(self, company: Company) -> BaseCrawler:
        match company.ats_type:
            case "greenhouse": return GreenhouseCrawler()
            case "lever":      return LeverCrawler()
            case "ashby":      return AshbyCrawler()
            case _:            return GenericCrawler()
```

| ATS | Reliability | Notes |
|---|---|---|
| Greenhouse | ★★★★★ | Structured JSON, no auth |
| Lever | ★★★★★ | Structured JSON, no auth |
| Ashby | ★★★★☆ | JSON API, minor variation per org |
| Generic | ★★★☆☆ | Fallback; flaky; flag for review |

---

## Enrichment Agent Prompt (MVP)

Single-turn call, batches of ~10 postings. Returns a JSON array.

**System prompt:**
```
You are evaluating job postings for a candidate with the following profile:

{settings.user_profile}

For each posting, return a JSON object with:
- fit_score: integer 1-5 (5 = near-perfect fit, 1 = poor fit)
- role_tier: "strong_match" | "match" | "reach"
- fit_reason: one sentence explaining the score
- key_requirements: array of 3-5 key requirements from the posting

Be honest about mismatches. A 3 is a genuine maybe.
Scores of 4-5 are reserved for close technical and seniority matches.

Return a JSON array in the same order as input. No preamble, valid JSON only.
```
