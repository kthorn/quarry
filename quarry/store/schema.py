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
