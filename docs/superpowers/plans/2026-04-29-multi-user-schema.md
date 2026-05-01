# Multi-User Schema — Shared Catalog + Per-User Data (Phase 1 of 4)

**Status:** Draft

**Parent:** [`2026-04-29-multi-user-architecture.md`](./2026-04-29-multi-user-architecture.md) — Phased roadmap: DDL → ORM → CRUD → callers

**Goal:** Redesign the SQLite schema to cleanly separate shared catalog data (companies, job postings, locations) from per-user preferences and ratings (watchlist, labels, posting status, similarity scores, settings). This is the foundational schema change that enables true multi-user support — most critically, **positive and negative ratings (labels) of job postings are per-user**, meaning different users can independently rate the same job posting.

This spec covers **Phase 1 only: raw DDL schema creation and test validation**. Subsequent phases (SQLAlchemy 2.0 + Alembic adoption, ORM CRUD rewrite, caller updates) are in the parent architecture document.

**Tech Stack:** Python 3.13, SQLite (with `PRAGMA foreign_keys = ON`), Pydantic

**Design Principle:** Shared tables hold canonical, user-independent data. Per-user tables hold preferences, computed scores, labels, and settings. All foreign keys use `ON DELETE CASCADE` (from shared → per-user) so deleting a company or posting cleans up all associated per-user data.

---

## Motivation: Why Per-User Ratings?

In the current schema, `labels` and `job_postings.status` are global — there's no concept of _who_ rated or acted on a posting. This means:

- If User A marks a posting as "applied" and User B hasn't seen it yet, User B's view is affected
- Positive/negative labels are shared across all users, so training a classifier from labels mixes signals
- Watchlist (`companies.active`) is global — User A's decision to deactivate a company affects User B

The new schema fixes this by assigning every preference, rating, and score to a specific `user_id`. In single-user mode (the only mode until auth is added), everything defaults to `user_id=1`.

---

## Schema Design

### Shared Catalog Tables (no user data)

These tables hold canonical data that is the same regardless of which user is viewing:

#### `companies` — Company directory

```
id, name, domain, careers_url, ats_type, ats_slug, resolve_status,
resolve_attempts, created_at, updated_at
```

**Removed from current schema:** `active`, `crawl_priority`, `notes`, `added_by`, `added_reason`, `last_crawled_at`
These all move to `user_watchlist`.

#### `job_postings` — Job postings catalog

```
id, company_id (FK → companies), title, title_hash, url, description,
location, work_model, posted_at, source_id, source_type,
embedding (BLOB), first_seen_at, last_seen_at
UNIQUE(company_id, title_hash)
```

**Removed from current schema:** `similarity_score`, `classifier_score`, `fit_score`, `role_tier`, `fit_reason`, `key_requirements`, `enriched_at`, `status`
Scores and enrichment move to per-user tables. Status moves to `user_posting_status`.

#### `locations` — Geo data (unchanged)

```
id, canonical_name (UNIQUE), city, state, state_code, country,
country_code, region, latitude, longitude, resolution_status, raw_fragment
```

#### `job_posting_locations` — Junction table (unchanged)

```
posting_id (FK → job_postings), location_id (FK → locations)
PRIMARY KEY(posting_id, location_id)
```

#### `crawl_runs` — System-level crawl history (unchanged)

```
id, company_id (FK → companies), started_at, completed_at, status,
postings_found, postings_new, error_message
```

#### `classifier_versions` — System-level trained models (unchanged)

```
id, trained_at, training_samples, positive_samples, negative_samples,
cv_accuracy, cv_precision, cv_recall, model_path, active, notes
```

#### `agent_actions` — System-level agent log (unchanged)

```
id, run_id, tool_name, tool_args, tool_result, rationale, created_at
```

#### `system_settings` — Global settings (replaces old `settings` table)

```
key (TEXT PRIMARY KEY), value (TEXT), updated_at
```

Stores schema version and other system-wide configuration. Per-user settings move to `user_settings`.

### Per-User Tables

These tables all have a `user_id` column and FK cascade from the `users` table:

#### `users` — User accounts

```sql
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    name        TEXT,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed a default user for single-user mode
INSERT OR IGNORE INTO users (id, email, name) VALUES (1, 'default@local', 'Default User');
```

#### `user_watchlist` — Which companies each user cares about

Replaces `companies.active`, `companies.crawl_priority`, `companies.notes`, `companies.added_by`, `companies.added_reason`.

```sql
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
```

#### `user_posting_status` — Per-user seen/applied/rejected/archived state

Replaces `job_postings.status`.

```sql
CREATE TABLE IF NOT EXISTS user_posting_status (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    posting_id      INTEGER NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    status          TEXT DEFAULT 'new' CHECK(status IN ('new','seen','applied','rejected','archived')),
    first_seen_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, posting_id)
);
```

#### `user_labels` — Per-user positive/negative ratings ★

This is the key table that enables per-user ratings. Replaces the global `labels` table.

```sql
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
```

**Key design decision:** `UNIQUE(user_id, posting_id, signal)` means a user can have both a `positive` and `applied` label on the same posting (they're different signals, and applied → positive is the label source analysis, not a given). It also means a user _cannot_ have two `positive` labels on the same posting (prevents double-positive from bugs).

#### `user_search_queries` — Per-user job board search queries

Replaces the global `search_queries` table.

```sql
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
```

**Removed from current `search_queries`:** `added_by` (replaced by `user_id` FK).

#### `user_similarity_scores` — Per-user embedding similarity

Replaces `job_postings.similarity_score`. Different users have different ideal role descriptions, so similarity scores differ per user.

```sql
CREATE TABLE IF NOT EXISTS user_similarity_scores (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    posting_id      INTEGER NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    similarity_score REAL NOT NULL,
    computed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, posting_id)
);
```

#### `user_classifier_scores` — Per-user ML classifier scores

Replaces `job_postings.classifier_score`. Classifiers are trained on per-user labels, so scores are per-user.

```sql
CREATE TABLE IF NOT EXISTS user_classifier_scores (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    posting_id      INTEGER NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    classifier_score REAL NOT NULL,
    model_version_id INTEGER REFERENCES classifier_versions(id) ON DELETE SET NULL,
    computed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, posting_id)
);
```

**Note:** `model_version_id` uses `ON DELETE SET NULL` (not CASCADE) so scores survive model version deletion — they just lose their provenance.

#### `user_enriched_postings` — Per-user LLM enrichment

Replaces `job_postings.fit_score`, `job_postings.role_tier`, `job_postings.fit_reason`, `job_postings.key_requirements`. LLM enrichment ("is this a good fit for me?") is inherently per-user.

```sql
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
```

#### `user_settings` — Per-user configuration

Replaces the old `settings` table for user-specific config (ideal role description, similarity threshold overrides, filter config, etc.).

```sql
CREATE TABLE IF NOT EXISTS user_settings (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    value       TEXT,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, key)
);
```

### Indexes

```sql
-- Shared table indexes (keep existing + add new)
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

-- Per-user indexes
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
```

### Indexes Removed from Current Schema

- `idx_postings_status` — `status` column is removed from `job_postings`
- `idx_postings_tier` — `role_tier` column is removed from `job_postings`

---

## Full Schema SQL

The complete `SCHEMA_SQL` string that replaces the current `quarry/store/schema.py`:

```sql
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
```

---

## Changes from Current Schema (Summary)

| Current Table/Column            | New Location                              | Reason                                         |
| ------------------------------- | ----------------------------------------- | ---------------------------------------------- |
| `companies.active`              | `user_watchlist.active`                   | Per-user watchlist toggle                      |
| `companies.crawl_priority`      | `user_watchlist.crawl_priority`           | Per-user prioritization                        |
| `companies.notes`               | `user_watchlist.notes`                    | Per-user private notes                         |
| `companies.added_by`            | Removed                                   | Replaced by `user_watchlist.user_id` FK        |
| `companies.added_reason`        | `user_watchlist.added_reason`             | Per-user context                               |
| `companies.last_crawled_at`     | Removed                                   | System concern, in `crawl_runs`                |
| `job_postings.similarity_score` | `user_similarity_scores.similarity_score` | Depends on user's ideal role                   |
| `job_postings.classifier_score` | `user_classifier_scores.classifier_score` | Per-user classifier                            |
| `job_postings.fit_score`        | `user_enriched_postings.fit_score`        | Per-user LLM enrichment                        |
| `job_postings.role_tier`        | `user_enriched_postings.role_tier`        | Per-user LLM enrichment                        |
| `job_postings.fit_reason`       | `user_enriched_postings.fit_reason`       | Per-user LLM enrichment                        |
| `job_postings.key_requirements` | `user_enriched_postings.key_requirements` | Per-user LLM enrichment                        |
| `job_postings.enriched_at`      | `user_enriched_postings.enriched_at`      | Per-user LLM enrichment                        |
| `job_postings.status`           | `user_posting_status.status`              | Per-user seen/applied/rejected/archived state  |
| `labels` (global table)         | `user_labels`                             | Per-user positive/negative ratings             |
| `search_queries` (global table) | `user_search_queries`                     | Per-user job board searches                    |
| `search_queries.added_by`       | Removed                                   | Replaced by `user_id` FK                       |
| `settings` (global table)       | `system_settings` + `user_settings`       | System vs per-user config split                |
| `idx_postings_status`           | Removed                                   | Status column removed from `job_postings`      |
| `idx_postings_tier`             | Removed                                   | `role_tier` column removed from `job_postings` |

---

## Implementation Plan

### Task 1: Rewrite `quarry/store/schema.py`

Replace the current `SCHEMA_SQL` string with the full schema above.

- [ ] Write the new `SCHEMA_SQL` with all shared + per-user tables and indexes
- [ ] Ensure `CHECK` constraints are on `ats_type`, `resolve_status`, `status`, `signal`
- [ ] Ensure all FKs have `ON DELETE CASCADE` except `model_version_id` (`ON DELETE SET NULL`)
- [ ] Include the `INSERT OR IGNORE INTO users` seed for the default user (id=1)

### Task 2: Backup & Delete Old DB

- [ ] Backup: `cp quarry.db quarry.db.backup.$(date +%Y%m%d_%H%M)`
- [ ] Delete old DB from git: `git rm quarry.db && git commit -m "data: delete old quarry.db for schema rebuild"`

### Task 3: Init New DB & Verify Schema

- [ ] Run `python -m quarry.store init` to create the new DB
- [ ] Verify all tables exist with correct columns
- [ ] Stage: `git add quarry.db && git commit -m "data: regenerate quarry.db with multi-user schema"`

### Task 4: Write Schema Tests

Write `tests/test_db.py` tests that verify:

- [ ] **Schema creation:** `init_db()` creates all expected tables (shared + per-user)
- [ ] **Default user seeded:** `SELECT * FROM users WHERE id = 1` returns one row
- [ ] **FK cascade delete:** Deleting a company cascades to `job_postings`, which cascades to `user_posting_status`, `user_labels`, `user_similarity_scores`, etc.
- [ ] **Per-user isolation:** User 1's labels don't appear in User 2's label queries
- [ ] **Per-user isolation:** User 1's posting status doesn't affect User 2's status
- [ ] **Per-user isolation:** User 1's watchlist is independent of User 2's
- [ ] **UNIQUE constraint on user_labels:** Inserting two labels with same (user_id, posting_id, signal) fails
- [ ] **CHECK constraint on user_labels.signal:** Inserting invalid signal fails
- [ ] **CHECK constraint on user_posting_status.status:** Inserting invalid status fails
- [ ] **CHECK constraint on companies.ats_type:** Inserting invalid ATS type fails
- [ ] **CHECK constraint on companies.resolve_status:** Inserting invalid resolve status fails

Example test:

```python
def test_multi_user_label_isolation(tmp_path):
    """User 1's labels are not visible to User 2."""
    db = init_db(tmp_path / "test.db")

    # Set up: company + posting
    db.insert_company(Company(name="Acme"))
    db.insert_posting(JobPosting(
        company_id=1, title="Engineer", title_hash="abc", url="http://x.com"
    ))

    # User 1 rates positively
    db.execute(
        "INSERT INTO user_labels (user_id, posting_id, signal) VALUES (1, 1, 'positive')"
    )

    # User 2 rates negatively on the SAME posting
    db.execute(
        "INSERT INTO user_labels (user_id, posting_id, signal) VALUES (2, 1, 'negative')"
    )

    # User 1 sees only their positive label
    u1_labels = db.execute(
        "SELECT signal FROM user_labels WHERE user_id = 1 AND posting_id = 1"
    )
    assert len(u1_labels) == 1
    assert u1_labels[0]["signal"] == "positive"

    # User 2 sees only their negative label
    u2_labels = db.execute(
        "SELECT signal FROM user_labels WHERE user_id = 2 AND posting_id = 1"
    )
    assert len(u2_labels) == 1
    assert u2_labels[0]["signal"] == "negative"
```

### Task 5: Remove `migrate_resolve_columns()`

- [ ] Remove the `migrate_resolve_columns()` method from `quarry/store/db.py` and `init_db()`. The new schema already has `resolve_status` and `resolve_attempts` columns, so this migration is dead code.
- [ ] Remove the corresponding test `test_migrate_resolve_columns` from `tests/test_db.py`

### Task 6: Commit

```bash
git add quarry/store/schema.py quarry/store/db.py quarry.db tests/test_db.py
git commit -m "feat: multi-user schema with per-user labels, status, and scores

Shared catalog: companies, job_postings, locations, crawl_runs,
  classifier_versions, agent_actions, system_settings
Per-user: users, user_watchlist, user_posting_status, user_labels,
  user_search_queries, user_similarity_scores, user_classifier_scores,
  user_enriched_postings, user_settings

Key design: positive/negative labels are per-user (user_labels),
enabling independent ratings across users. All FKs use ON DELETE CASCADE
except model_version_id (SET NULL). Default user_id=1 seeded for
single-user compatibility."
```

---

## What This Spec Does NOT Cover

This spec is **Phase 1 of 4** — intentionally scoped to raw DDL schema creation only. The following are covered in the parent architecture document:

| Phase   | What                                                               | Document                                                                                                             |
| ------- | ------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| Phase 2 | SQLAlchemy 2.0 ORM models + Alembic migrations                     | `2026-04-29-multi-user-architecture.md`                                                                              |
| Phase 3 | Rewrite `db.py` CRUD with ORM queries                              | `2026-04-29-multi-user-architecture.md`                                                                              |
| Phase 4 | Update callers: models, scheduler, UI, CLIs, digest, config, tests | `2026-04-29-multi-user-architecture.md` (with per-file detail in `2026-04-28-schema-rebuild-multiuser.md` Tasks 2–9) |

Deferred work includes:

- Pydantic API model updates, DB CRUD rewrites, scheduler/user_id propagation, UI routes/templates, CLI entrypoints, seed data loader, config migration, digest/filter modules, and all test updates.

---

## Verification Commands

```bash
# After schema is written:
python -m quarry.store init       # Creates new quarry.db
python -m pytest tests/test_db.py -q  # Schema tests pass
sqlite3 quarry.db ".schema"       # Visually verify schema
```
