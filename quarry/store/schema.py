# quarry/store/schema.py
"""Multi-user database schema — shared catalog + per-user data.

Phase 1 of 4 (DDL only). See docs/multi-user-schema.md for full
documentation and ERD.
"""

SCHEMA_SQL = """
-- ============================================================
-- Shared Catalog Tables (user-independent canonical data)
-- ============================================================

CREATE TABLE IF NOT EXISTS companies (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    domain          TEXT,
    careers_url     TEXT,
    ats_type        TEXT DEFAULT 'unknown' CHECK(ats_type IN ('greenhouse','lever','ashby','generic','unknown')),
    ats_slug        TEXT,
    resolve_status  TEXT DEFAULT 'unresolved' CHECK(resolve_status IN ('unresolved','resolved','failed')),
    resolve_attempts INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_postings (
    id              INTEGER PRIMARY KEY,
    company_id      INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    title_hash      TEXT NOT NULL,
    url             TEXT NOT NULL,
    description     TEXT,
    location        TEXT,
    work_model      TEXT,
    posted_at       TIMESTAMP,
    source_id       TEXT,
    source_type     TEXT,
    embedding       BLOB,
    first_seen_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, title_hash)
);

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

CREATE TABLE IF NOT EXISTS job_posting_locations (
    posting_id  INTEGER NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    PRIMARY KEY (posting_id, location_id)
);

CREATE TABLE IF NOT EXISTS crawl_runs (
    id              INTEGER PRIMARY KEY,
    company_id      INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    status          TEXT,
    postings_found  INTEGER DEFAULT 0,
    postings_new    INTEGER DEFAULT 0,
    error_message   TEXT
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

-- WARNING: tool_args and tool_result may contain sensitive data (API keys,
-- resume text, LLM prompts). Stored as plaintext. Encrypt or mask before
-- multi-user deployment if this data crosses trust boundaries.
CREATE TABLE IF NOT EXISTS agent_actions (
    id          INTEGER PRIMARY KEY,
    run_id      TEXT,
    tool_name   TEXT NOT NULL,
    tool_args   TEXT,
    tool_result TEXT,
    rationale   TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS system_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- Per-User Tables (preferences, ratings, scores, settings)
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    name            TEXT,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO users (id, email, name) VALUES (1, 'default@local', 'Default User');

CREATE TABLE IF NOT EXISTS user_watchlist (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_id      INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    active          BOOLEAN DEFAULT TRUE,
    crawl_priority  INTEGER DEFAULT 5,
    notes           TEXT,
    added_reason    TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, company_id)
);

CREATE TABLE IF NOT EXISTS user_posting_status (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    posting_id      INTEGER NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    status          TEXT DEFAULT 'new' CHECK(status IN ('new','seen','applied','rejected','archived')),
    first_seen_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, posting_id)
);

CREATE TABLE IF NOT EXISTS user_labels (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    posting_id      INTEGER NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    signal          TEXT NOT NULL CHECK(signal IN ('positive','negative','applied','skip')),
    notes           TEXT,
    labeled_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    label_source    TEXT DEFAULT 'user',
    UNIQUE(user_id, posting_id, signal)
);

CREATE TABLE IF NOT EXISTS user_search_queries (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    query_text      TEXT NOT NULL,
    site            TEXT,
    active          BOOLEAN DEFAULT TRUE,
    added_reason    TEXT,
    retired_reason  TEXT,
    postings_found  INTEGER DEFAULT 0,
    positive_labels INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, query_text)
);

CREATE TABLE IF NOT EXISTS user_similarity_scores (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    posting_id      INTEGER NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    similarity_score REAL NOT NULL,
    computed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, posting_id)
);

CREATE TABLE IF NOT EXISTS user_classifier_scores (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    posting_id      INTEGER NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    classifier_score REAL NOT NULL,
    model_version_id INTEGER REFERENCES classifier_versions(id) ON DELETE SET NULL,
    computed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, posting_id)
);

CREATE TABLE IF NOT EXISTS user_enriched_postings (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    posting_id      INTEGER NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    fit_score       INTEGER,
    role_tier       TEXT,
    fit_reason      TEXT,
    key_requirements TEXT,
    enriched_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, posting_id)
);

CREATE TABLE IF NOT EXISTS user_settings (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    value       TEXT,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, key)
);

-- ============================================================
-- Indexes
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_postings_company ON job_postings(company_id);
CREATE INDEX IF NOT EXISTS idx_postings_title_hash ON job_postings(title_hash);
CREATE INDEX IF NOT EXISTS idx_postings_work_model ON job_postings(work_model);

CREATE INDEX IF NOT EXISTS idx_locations_canonical ON locations(canonical_name);
CREATE INDEX IF NOT EXISTS idx_locations_country ON locations(country_code);
CREATE INDEX IF NOT EXISTS idx_locations_region ON locations(region);
CREATE INDEX IF NOT EXISTS idx_locations_city ON locations(city);
CREATE INDEX IF NOT EXISTS idx_locations_state ON locations(state_code);

CREATE INDEX IF NOT EXISTS idx_jpl_posting ON job_posting_locations(posting_id);
CREATE INDEX IF NOT EXISTS idx_jpl_location ON job_posting_locations(location_id);

CREATE INDEX IF NOT EXISTS idx_agent_actions_run ON agent_actions(run_id);
CREATE INDEX IF NOT EXISTS idx_agent_actions_time ON agent_actions(created_at);

CREATE INDEX IF NOT EXISTS idx_watchlist_user ON user_watchlist(user_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_company ON user_watchlist(company_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_active ON user_watchlist(user_id, active);

CREATE INDEX IF NOT EXISTS idx_posting_status_user ON user_posting_status(user_id);
CREATE INDEX IF NOT EXISTS idx_posting_status_posting ON user_posting_status(posting_id);
CREATE INDEX IF NOT EXISTS idx_posting_status_status ON user_posting_status(user_id, status);

CREATE INDEX IF NOT EXISTS idx_labels_user ON user_labels(user_id);
CREATE INDEX IF NOT EXISTS idx_labels_posting ON user_labels(posting_id);

CREATE INDEX IF NOT EXISTS idx_sim_scores_user ON user_similarity_scores(user_id);
CREATE INDEX IF NOT EXISTS idx_sim_scores_posting ON user_similarity_scores(posting_id);
CREATE INDEX IF NOT EXISTS idx_sim_scores_value ON user_similarity_scores(user_id, similarity_score);

CREATE INDEX IF NOT EXISTS idx_cls_scores_user ON user_classifier_scores(user_id);
CREATE INDEX IF NOT EXISTS idx_cls_scores_posting ON user_classifier_scores(posting_id);

CREATE INDEX IF NOT EXISTS idx_enriched_user ON user_enriched_postings(user_id);
CREATE INDEX IF NOT EXISTS idx_enriched_posting ON user_enriched_postings(posting_id);
"""
