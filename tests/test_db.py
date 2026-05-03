"""Schema tests for multi-user DDL (Phase 1).

Tests verify:
- All shared + per-user tables are created
- Default user (id=1) is seeded
- Foreign key cascade delete behavior
- Per-user data isolation (labels, status, watchlist)
- UNIQUE constraints
- CHECK constraints
"""

import sqlite3

import pytest

from quarry import models
from quarry.store.db import Database, init_db

# ── Table creation ──────────────────────────────────────────────


def test_init_creates_all_shared_tables(tmp_path):
    """init_db() creates all shared catalog tables."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()

    shared_tables = [
        "companies",
        "job_postings",
        "locations",
        "job_posting_locations",
        "crawl_runs",
        "classifier_versions",
        "agent_actions",
        "system_settings",
    ]
    for table in shared_tables:
        assert table in tables, f"Missing shared table: {table}"


def test_init_creates_all_per_user_tables(tmp_path):
    """init_db() creates all per-user tables."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()

    per_user_tables = [
        "users",
        "user_watchlist",
        "user_posting_status",
        "user_labels",
        "user_search_queries",
        "user_similarity_scores",
        "user_classifier_scores",
        "user_enriched_postings",
        "user_settings",
    ]
    for table in per_user_tables:
        assert table in tables, f"Missing per-user table: {table}"


def test_init_does_not_create_old_tables(tmp_path):
    """Old global tables (labels, search_queries, settings) are not created."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()

    assert "labels" not in tables, "Old 'labels' table still exists"
    assert "search_queries" not in tables, "Old 'search_queries' table still exists"
    assert "settings" not in tables, "Old 'settings' table still exists"


# ── Default user seed ───────────────────────────────────────────


def test_default_user_seeded(tmp_path):
    """Default user (id=1) is seeded on init."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM users WHERE id = 1").fetchone()
    conn.close()

    assert row is not None, "Default user not seeded"
    assert row["id"] == 1
    assert row["email"] == "default@local"
    assert row["name"] == "Default User"
    assert row["is_active"] == 1


def test_init_twice_does_not_duplicate_default_user(tmp_path):
    """Calling init_db() twice does not create duplicate default users."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    init_db(db_path)  # Second call should be idempotent

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    conn.close()

    assert count == 1, f"Expected 1 user, got {count}"


# ── Foreign key cascade delete ──────────────────────────────────


def test_fk_cascade_delete_company_to_postings(tmp_path):
    """Deleting a company cascades to its job postings."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("INSERT INTO companies (name) VALUES ('Acme')")
    conn.execute("""INSERT INTO job_postings (company_id, title, title_hash, url)
                    VALUES (1, 'Engineer', 'abc', 'http://x.com')""")
    conn.commit()

    conn.execute("DELETE FROM companies WHERE id = 1")

    cursor = conn.execute("SELECT COUNT(*) FROM job_postings")
    assert cursor.fetchone()[0] == 0, "Postings not cascade-deleted"
    conn.close()


def test_fk_cascade_postings_to_per_user_tables(tmp_path):
    """Deleting a job posting cascades to all per-user tables that reference it."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    # Setup
    conn.execute("INSERT INTO companies (name) VALUES ('Acme')")
    conn.execute("""INSERT INTO job_postings (company_id, title, title_hash, url)
                    VALUES (1, 'Engineer', 'abc', 'http://x.com')""")
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (1, 'a@b.com')")

    # Insert per-user data
    conn.execute("INSERT INTO user_posting_status (user_id, posting_id) VALUES (1, 1)")
    conn.execute(
        "INSERT INTO user_labels (user_id, posting_id, signal) VALUES (1, 1, 'positive')"
    )
    conn.execute(
        "INSERT INTO user_similarity_scores (user_id, posting_id, similarity_score) VALUES (1, 1, 0.95)"
    )
    conn.execute(
        "INSERT INTO user_classifier_scores (user_id, posting_id, classifier_score) VALUES (1, 1, 0.8)"
    )
    conn.execute(
        "INSERT INTO user_enriched_postings (user_id, posting_id) VALUES (1, 1)"
    )
    conn.commit()

    # Delete posting
    conn.execute("DELETE FROM job_postings WHERE id = 1")

    # Verify cascade
    for table in [
        "user_posting_status",
        "user_labels",
        "user_similarity_scores",
        "user_classifier_scores",
        "user_enriched_postings",
    ]:
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        assert count == 0, f"{table} not cascade-deleted from postings"

    conn.close()


def test_fk_cascade_user_to_per_user_tables(tmp_path):
    """Deleting a user cascades to all their per-user data."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    # Setup
    conn.execute("INSERT INTO companies (name) VALUES ('Acme')")
    conn.execute("""INSERT INTO job_postings (company_id, title, title_hash, url)
                    VALUES (1, 'Engineer', 'abc', 'http://x.com')""")
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (1, 'user1@b.com')")

    # Insert per-user data in all tables
    conn.execute("INSERT INTO user_watchlist (user_id, company_id) VALUES (1, 1)")
    conn.execute("INSERT INTO user_posting_status (user_id, posting_id) VALUES (1, 1)")
    conn.execute(
        "INSERT INTO user_labels (user_id, posting_id, signal) VALUES (1, 1, 'positive')"
    )
    conn.execute(
        "INSERT INTO user_search_queries (user_id, query_text) VALUES (1, 'test')"
    )
    conn.execute(
        "INSERT INTO user_similarity_scores (user_id, posting_id, similarity_score) VALUES (1, 1, 0.9)"
    )
    conn.execute(
        "INSERT INTO user_classifier_scores (user_id, posting_id, classifier_score) VALUES (1, 1, 0.7)"
    )
    conn.execute(
        "INSERT INTO user_enriched_postings (user_id, posting_id) VALUES (1, 1)"
    )
    conn.execute(
        "INSERT INTO user_settings (user_id, key, value) VALUES (1, 'theme', 'dark')"
    )
    conn.commit()

    # Delete user
    conn.execute("DELETE FROM users WHERE id = 1")

    # Verify cascade
    per_user_tables = [
        "user_watchlist",
        "user_posting_status",
        "user_labels",
        "user_search_queries",
        "user_similarity_scores",
        "user_classifier_scores",
        "user_enriched_postings",
        "user_settings",
    ]
    for table in per_user_tables:
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        assert count == 0, f"{table} not cascade-deleted from users"

    conn.close()


def test_classifier_scores_survive_model_deletion(tmp_path):
    """user_classifier_scores survive when the classifier version is deleted (SET NULL)."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    # Setup
    conn.execute("INSERT INTO classifier_versions (id, notes) VALUES (1, 'v1')")
    conn.execute("INSERT INTO companies (name) VALUES ('Acme')")
    conn.execute("""INSERT INTO job_postings (company_id, title, title_hash, url)
                    VALUES (1, 'Engineer', 'abc', 'http://x.com')""")
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (1, 'a@b.com')")
    conn.execute(
        "INSERT INTO user_classifier_scores (user_id, posting_id, classifier_score, model_version_id) "
        "VALUES (1, 1, 0.9, 1)"
    )
    conn.commit()

    # Delete model version
    conn.execute("DELETE FROM classifier_versions WHERE id = 1")

    # Score should survive with model_version_id set to NULL
    row = conn.execute(
        "SELECT classifier_score, model_version_id FROM user_classifier_scores WHERE id = 1"
    ).fetchone()
    assert row is not None, "Score was deleted (should survive)"
    assert row[0] == 0.9, "Score value changed"
    assert row[1] is None, "model_version_id should be NULL"

    conn.close()


# ── Per-user data isolation ─────────────────────────────────────


def test_multi_user_label_isolation(tmp_path):
    """User 1's labels are not visible to User 2."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    # Setup: company + posting + second user
    conn.execute("INSERT INTO companies (name) VALUES ('Acme')")
    conn.execute("""INSERT INTO job_postings (company_id, title, title_hash, url)
                    VALUES (1, 'Engineer', 'abc', 'http://x.com')""")
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (1, 'u1@b.com')")
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (2, 'u2@b.com')")

    # User 1 rates positively, User 2 rates negatively on SAME posting
    conn.execute(
        "INSERT INTO user_labels (user_id, posting_id, signal) VALUES (1, 1, 'positive')"
    )
    conn.execute(
        "INSERT INTO user_labels (user_id, posting_id, signal) VALUES (2, 1, 'negative')"
    )
    conn.commit()

    # User 1 sees only their positive label
    u1_labels = conn.execute(
        "SELECT signal FROM user_labels WHERE user_id = 1 AND posting_id = 1"
    ).fetchall()
    assert len(u1_labels) == 1
    assert u1_labels[0][0] == "positive"

    # User 2 sees only their negative label
    u2_labels = conn.execute(
        "SELECT signal FROM user_labels WHERE user_id = 2 AND posting_id = 1"
    ).fetchall()
    assert len(u2_labels) == 1
    assert u2_labels[0][0] == "negative"

    conn.close()


def test_multi_user_posting_status_isolation(tmp_path):
    """User 1's posting status does not affect User 2's status."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("INSERT INTO companies (name) VALUES ('Acme')")
    conn.execute("""INSERT INTO job_postings (company_id, title, title_hash, url)
                    VALUES (1, 'Engineer', 'abc', 'http://x.com')""")
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (1, 'u1@b.com')")
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (2, 'u2@b.com')")

    # User 1 marks as applied, User 2 hasn't seen it
    conn.execute(
        "INSERT INTO user_posting_status (user_id, posting_id, status) VALUES (1, 1, 'applied')"
    )
    conn.execute(
        "INSERT INTO user_posting_status (user_id, posting_id, status) VALUES (2, 1, 'new')"
    )
    conn.commit()

    u1_status = conn.execute(
        "SELECT status FROM user_posting_status WHERE user_id = 1 AND posting_id = 1"
    ).fetchone()
    u2_status = conn.execute(
        "SELECT status FROM user_posting_status WHERE user_id = 2 AND posting_id = 1"
    ).fetchone()

    assert u1_status[0] == "applied"
    assert u2_status[0] == "new"

    conn.close()


def test_multi_user_watchlist_isolation(tmp_path):
    """User 1's watchlist is independent of User 2's."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("INSERT INTO companies (name) VALUES ('Acme')")
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (1, 'u1@b.com')")
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (2, 'u2@b.com')")

    # User 1 deactivates Acme, User 2 keeps it active
    conn.execute(
        "INSERT INTO user_watchlist (user_id, company_id, active) VALUES (1, 1, 0)"
    )
    conn.execute(
        "INSERT INTO user_watchlist (user_id, company_id, active) VALUES (2, 1, 1)"
    )
    conn.commit()

    u1_active = conn.execute(
        "SELECT active FROM user_watchlist WHERE user_id = 1 AND company_id = 1"
    ).fetchone()
    u2_active = conn.execute(
        "SELECT active FROM user_watchlist WHERE user_id = 2 AND company_id = 1"
    ).fetchone()

    assert u1_active[0] == 0, "User 1 should see inactive"
    assert u2_active[0] == 1, "User 2 should see active"

    conn.close()


def test_multi_user_similarity_score_isolation(tmp_path):
    """Similarity scores are per-user (different ideal roles → different scores)."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("INSERT INTO companies (name) VALUES ('Acme')")
    conn.execute("""INSERT INTO job_postings (company_id, title, title_hash, url)
                    VALUES (1, 'Engineer', 'abc', 'http://x.com')""")
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (1, 'u1@b.com')")
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (2, 'u2@b.com')")

    conn.execute(
        "INSERT INTO user_similarity_scores (user_id, posting_id, similarity_score) VALUES (1, 1, 0.85)"
    )
    conn.execute(
        "INSERT INTO user_similarity_scores (user_id, posting_id, similarity_score) VALUES (2, 1, 0.42)"
    )
    conn.commit()

    u1_score = conn.execute(
        "SELECT similarity_score FROM user_similarity_scores WHERE user_id = 1 AND posting_id = 1"
    ).fetchone()
    u2_score = conn.execute(
        "SELECT similarity_score FROM user_similarity_scores WHERE user_id = 2 AND posting_id = 1"
    ).fetchone()

    assert u1_score[0] == 0.85
    assert u2_score[0] == 0.42

    conn.close()


# ── UNIQUE constraints ──────────────────────────────────────────


def test_user_labels_unique_constraint(tmp_path):
    """UNIQUE(user_id, posting_id, signal) prevents duplicate labels."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("INSERT INTO companies (name) VALUES ('Acme')")
    conn.execute("""INSERT INTO job_postings (company_id, title, title_hash, url)
                    VALUES (1, 'Engineer', 'abc', 'http://x.com')""")
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (1, 'u1@b.com')")

    conn.execute(
        "INSERT INTO user_labels (user_id, posting_id, signal) VALUES (1, 1, 'positive')"
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO user_labels (user_id, posting_id, signal) VALUES (1, 1, 'positive')"
        )

    conn.close()


def test_user_labels_allows_different_signals_on_same_posting(tmp_path):
    """A user can have multiple signal types on the same posting (positive + applied)."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("INSERT INTO companies (name) VALUES ('Acme')")
    conn.execute("""INSERT INTO job_postings (company_id, title, title_hash, url)
                    VALUES (1, 'Engineer', 'abc', 'http://x.com')""")
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (1, 'u1@b.com')")

    # Both should succeed — different signals
    conn.execute(
        "INSERT INTO user_labels (user_id, posting_id, signal) VALUES (1, 1, 'positive')"
    )
    conn.execute(
        "INSERT INTO user_labels (user_id, posting_id, signal) VALUES (1, 1, 'applied')"
    )
    conn.commit()

    labels = conn.execute(
        "SELECT signal FROM user_labels WHERE user_id = 1 AND posting_id = 1 ORDER BY signal"
    ).fetchall()
    assert len(labels) == 2
    assert labels[0][0] == "applied"
    assert labels[1][0] == "positive"

    conn.close()


def test_user_watchlist_unique_constraint(tmp_path):
    """UNIQUE(user_id, company_id) prevents duplicate watchlist entries."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("INSERT INTO companies (name) VALUES ('Acme')")
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (1, 'u1@b.com')")

    conn.execute("INSERT INTO user_watchlist (user_id, company_id) VALUES (1, 1)")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO user_watchlist (user_id, company_id) VALUES (1, 1)")

    conn.close()


def test_user_posting_status_unique_constraint(tmp_path):
    """UNIQUE(user_id, posting_id) prevents duplicate status entries."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("INSERT INTO companies (name) VALUES ('Acme')")
    conn.execute("""INSERT INTO job_postings (company_id, title, title_hash, url)
                    VALUES (1, 'Engineer', 'abc', 'http://x.com')""")
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (1, 'u1@b.com')")

    conn.execute("INSERT INTO user_posting_status (user_id, posting_id) VALUES (1, 1)")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO user_posting_status (user_id, posting_id) VALUES (1, 1)"
        )

    conn.close()


# ── CHECK constraints ───────────────────────────────────────────


def test_check_constraint_user_labels_signal_invalid(tmp_path):
    """CHECK on user_labels.signal rejects invalid values."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("INSERT INTO companies (name) VALUES ('Acme')")
    conn.execute("""INSERT INTO job_postings (company_id, title, title_hash, url)
                    VALUES (1, 'Engineer', 'abc', 'http://x.com')""")
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (1, 'u1@b.com')")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO user_labels (user_id, posting_id, signal) VALUES (1, 1, 'invalid_signal')"
        )

    conn.close()


def test_check_constraint_user_labels_signal_valid(tmp_path):
    """Verify all valid signals are accepted."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("INSERT INTO companies (name) VALUES ('Acme')")
    conn.execute("""INSERT INTO job_postings (company_id, title, title_hash, url)
                    VALUES (1, 'Engineer', 'abc', 'http://x.com')""")
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (1, 'u1@b.com')")

    for signal in ["positive", "negative", "applied", "skip"]:
        conn.execute(
            f"INSERT INTO user_labels (user_id, posting_id, signal) VALUES (1, 1, '{signal}')"
        )

    count = conn.execute(
        "SELECT COUNT(*) FROM user_labels WHERE user_id = 1 AND posting_id = 1"
    ).fetchone()[0]
    assert count == 4, f"Expected 4 signals, got {count}"

    conn.close()


def test_check_constraint_user_posting_status_invalid(tmp_path):
    """CHECK on user_posting_status.status rejects invalid values."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("INSERT INTO companies (name) VALUES ('Acme')")
    conn.execute("""INSERT INTO job_postings (company_id, title, title_hash, url)
                    VALUES (1, 'Engineer', 'abc', 'http://x.com')""")
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (1, 'u1@b.com')")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO user_posting_status (user_id, posting_id, status) VALUES (1, 1, 'bogus')"
        )

    conn.close()


def test_check_constraint_companies_ats_type_invalid(tmp_path):
    """CHECK on companies.ats_type rejects invalid values."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO companies (name, ats_type) VALUES ('Test', 'workday')"
        )

    conn.close()


def test_check_constraint_companies_ats_type_valid(tmp_path):
    """All valid ATS types are accepted."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    for ats in ["greenhouse", "lever", "ashby", "generic", "unknown"]:
        conn.execute(
            f"INSERT INTO companies (name, ats_type) VALUES ('{ats}', '{ats}')"
        )

    count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    assert count == 5

    conn.close()


def test_check_constraint_companies_resolve_status_invalid(tmp_path):
    """CHECK on companies.resolve_status rejects invalid values."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO companies (name, resolve_status) VALUES ('Test', 'pending')"
        )

    conn.close()


# ── Column presence checks ──────────────────────────────────────


def test_job_postings_columns_exclude_old(tmp_path):
    """job_postings table does not have old per-user columns."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(job_postings)")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()

    removed_columns = {
        "similarity_score",
        "classifier_score",
        "fit_score",
        "role_tier",
        "fit_reason",
        "key_requirements",
        "enriched_at",
        "status",
    }
    for col in removed_columns:
        assert col not in columns, f"Old column '{col}' still in job_postings"


def test_companies_columns_exclude_old(tmp_path):
    """companies table does not have old per-user columns."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(companies)")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()

    removed_columns = {
        "active",
        "crawl_priority",
        "notes",
        "added_by",
        "added_reason",
        "last_crawled_at",
    }
    for col in removed_columns:
        assert col not in columns, f"Old column '{col}' still in companies"


# ── Index presence ──────────────────────────────────────────────


def test_old_indexes_not_present(tmp_path):
    """Indexes on removed columns (idx_postings_status, idx_postings_tier) are gone."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
    indexes = {row[0] for row in cursor.fetchall()}
    conn.close()

    assert "idx_postings_status" not in indexes, (
        "Old index idx_postings_status still present"
    )
    assert "idx_postings_tier" not in indexes, (
        "Old index idx_postings_tier still present"
    )


def test_per_user_indexes_present(tmp_path):
    """All new per-user indexes are created."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
    indexes = {row[0] for row in cursor.fetchall()}
    conn.close()

    expected = [
        "idx_watchlist_user",
        "idx_watchlist_company",
        "idx_watchlist_active",
        "idx_posting_status_user",
        "idx_posting_status_posting",
        "idx_posting_status_status",
        "idx_labels_user",
        "idx_labels_posting",
        "idx_sim_scores_user",
        "idx_sim_scores_posting",
        "idx_sim_scores_value",
        "idx_cls_scores_user",
        "idx_cls_scores_posting",
        "idx_enriched_user",
        "idx_enriched_posting",
    ]
    for idx in expected:
        assert idx in indexes, f"Missing index: {idx}"


# ── Foreign key presence ────────────────────────────────────────


def test_job_postings_company_id_not_null(tmp_path):
    """company_id in job_postings has NOT NULL constraint (new with multi-user schema)."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO job_postings (title, title_hash, url) VALUES ('Test', 'hash', 'http://x.com')"
        )

    conn.close()


# ════════════════════════════════════════════════════════════════
# Phase 3 CRUD Integration Tests
# ════════════════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path):
    """Return a fresh temp DB path (DB not yet created)."""
    return tmp_path / "test.db"


@pytest.fixture
def db(db_path):
    """Create a fresh DB with schema + default user, return Database instance."""
    init_db(db_path)
    return Database(db_path)


def _raw(db_path_v):
    """Open a raw sqlite3 connection on the test DB.

    NOTE: This bypasses the engine's FK enforcement pragma listener registered
    in quarry/store/session.py. Raw sqlite3 connections do NOT enforce foreign
    keys by default. This is intentional — it allows cross-user data setup
    (inserting data for user_id=2 without a users row) in isolation tests.
    """
    conn = sqlite3.connect(str(db_path_v))
    conn.row_factory = sqlite3.Row
    return conn


# ── Company CRUD ────────────────────────────────────────────────


def test_insert_and_get_company(db):
    company = models.Company(name="TestCo", domain="testco.com")
    cid = db.insert_company(company)
    assert cid > 0

    fetched = db.get_company(cid)
    assert fetched is not None
    assert fetched.name == "TestCo"
    assert fetched.domain == "testco.com"


def test_insert_company_creates_watchlist(db, db_path):
    cid = db.insert_company(models.Company(name="Acme"))
    conn = _raw(db_path)
    row = conn.execute(
        "SELECT * FROM user_watchlist WHERE user_id = 1 AND company_id = ?", (cid,)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["active"] == 1


def test_get_all_companies_active_only(db, db_path):
    db.insert_company(models.Company(name="ActiveCo"))
    cid2 = db.insert_company(models.Company(name="InactiveCo"))
    # Deactivate via raw sqlite3
    conn = _raw(db_path)
    conn.execute(
        "UPDATE user_watchlist SET active = 0 WHERE company_id = ? AND user_id = 1",
        (cid2,),
    )
    conn.commit()
    conn.close()

    active = db.get_all_companies(active_only=True)
    assert len(active) == 1
    assert active[0].name == "ActiveCo"


def test_get_all_companies_unfiltered(db):
    db.insert_company(models.Company(name="A"))
    db.insert_company(models.Company(name="B"))
    all_co = db.get_all_companies(active_only=False)
    assert len(all_co) == 2


def test_get_company_by_name(db):
    db.insert_company(models.Company(name="UniqueCorp"))
    found = db.get_company_by_name("UniqueCorp")
    assert found is not None
    assert found.name == "UniqueCorp"
    assert db.get_company_by_name("Nonexistent") is None


def test_get_companies_by_resolve_status(db):
    db.insert_company(models.Company(name="UnresolvedCo", resolve_status="unresolved"))
    db.insert_company(models.Company(name="ResolvedCo", resolve_status="resolved"))

    unresolved = db.get_companies_by_resolve_status("unresolved")
    assert len(unresolved) == 1
    assert unresolved[0].name == "UnresolvedCo"


def test_update_company(db):
    cid = db.insert_company(models.Company(name="Before"))
    company = db.get_company(cid)
    assert company is not None
    company.name = "After"
    company.domain = "after.com"
    db.update_company(company)

    updated = db.get_company(cid)
    assert updated is not None
    assert updated.name == "After"
    assert updated.domain == "after.com"


# ── Posting CRUD ───────────────────────────────────────────────


def test_insert_and_get_posting(db):
    cid = db.insert_company(models.Company(name="Acme"))
    posting = models.JobPosting(
        company_id=cid,
        title="Engineer",
        title_hash="abc123",
        url="http://example.com/job/1",
    )
    pid = db.insert_posting(posting)
    assert pid > 0

    fetched = db.get_posting_by_id(pid)
    assert fetched is not None
    assert fetched.title == "Engineer"


def test_insert_posting_creates_status(db, db_path):
    cid = db.insert_company(models.Company(name="Acme"))
    posting = models.JobPosting(
        company_id=cid, title="Engineer", title_hash="abc", url="http://x.com"
    )
    pid = db.insert_posting(posting)

    conn = _raw(db_path)
    row = conn.execute(
        "SELECT status FROM user_posting_status WHERE user_id = 1 AND posting_id = ?",
        (pid,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["status"] == "new"


def test_posting_exists(db):
    cid = db.insert_company(models.Company(name="Acme"))
    posting = models.JobPosting(
        company_id=cid, title="Engineer", title_hash="abc", url="http://x.com"
    )
    db.insert_posting(posting)

    assert db.posting_exists(cid, "abc") is True
    assert db.posting_exists(cid, "nonexistent") is False


def test_posting_exists_by_url(db):
    cid = db.insert_company(models.Company(name="Acme"))
    posting = models.JobPosting(
        company_id=cid, title="Engineer", title_hash="abc", url="http://x.com/job/1"
    )
    db.insert_posting(posting)

    assert db.posting_exists_by_url("http://x.com/job/1") is True
    assert db.posting_exists_by_url("http://x.com/job/2") is False


def test_update_posting_embedding(db, db_path):
    cid = db.insert_company(models.Company(name="Acme"))
    posting = models.JobPosting(
        company_id=cid, title="E", title_hash="h", url="http://x.com"
    )
    pid = db.insert_posting(posting)
    db.update_posting_embedding(pid, b"test_embedding")

    conn = _raw(db_path)
    row = conn.execute(
        "SELECT embedding FROM job_postings WHERE id = ?", (pid,)
    ).fetchone()
    conn.close()
    assert row["embedding"] == b"test_embedding"


def test_update_posting_similarity_writes_to_user_table(db, db_path):
    cid = db.insert_company(models.Company(name="Acme"))
    posting = models.JobPosting(
        company_id=cid, title="E", title_hash="h", url="http://x.com"
    )
    pid = db.insert_posting(posting)
    db.update_posting_similarity(pid, 0.95)

    conn = _raw(db_path)
    row = conn.execute(
        "SELECT similarity_score FROM user_similarity_scores WHERE user_id = 1 AND posting_id = ?",
        (pid,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["similarity_score"] == pytest.approx(0.95)


def test_update_posting_similarities_bulk(db, db_path):
    cid = db.insert_company(models.Company(name="Acme"))
    p1 = models.JobPosting(
        company_id=cid, title="A", title_hash="a", url="http://x.com/a"
    )
    p2 = models.JobPosting(
        company_id=cid, title="B", title_hash="b", url="http://x.com/b"
    )
    pid1 = db.insert_posting(p1)
    pid2 = db.insert_posting(p2)

    db.update_posting_similarities([(pid1, 0.5), (pid2, 0.8)])

    conn = _raw(db_path)
    rows = conn.execute(
        "SELECT posting_id, similarity_score FROM user_similarity_scores WHERE user_id = 1 ORDER BY posting_id"
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    assert float(rows[0]["similarity_score"]) == pytest.approx(0.5)
    assert float(rows[1]["similarity_score"]) == pytest.approx(0.8)


def test_mark_postings_seen(db, db_path):
    cid = db.insert_company(models.Company(name="Acme"))
    posting = models.JobPosting(
        company_id=cid, title="E", title_hash="h", url="http://x.com"
    )
    pid = db.insert_posting(posting)

    db.mark_postings_seen([pid])

    conn = _raw(db_path)
    row = conn.execute(
        "SELECT status FROM user_posting_status WHERE user_id = 1 AND posting_id = ?",
        (pid,),
    ).fetchone()
    conn.close()
    assert row["status"] == "seen"


def test_update_posting_status(db, db_path):
    cid = db.insert_company(models.Company(name="Acme"))
    posting = models.JobPosting(
        company_id=cid, title="E", title_hash="h", url="http://x.com"
    )
    pid = db.insert_posting(posting)

    db.update_posting_status(pid, "applied")

    conn = _raw(db_path)
    row = conn.execute(
        "SELECT status FROM user_posting_status WHERE user_id = 1 AND posting_id = ?",
        (pid,),
    ).fetchone()
    conn.close()
    assert row["status"] == "applied"


def test_count_postings(db):
    cid = db.insert_company(models.Company(name="Acme"))
    db.insert_posting(
        models.JobPosting(
            company_id=cid, title="A", title_hash="a", url="http://x.com/a"
        )
    )
    db.insert_posting(
        models.JobPosting(
            company_id=cid, title="B", title_hash="b", url="http://x.com/b"
        )
    )

    assert db.count_postings() == 2
    assert db.count_postings(status="new") == 2
    assert db.count_postings(status="seen") == 0


def test_get_postings_with_scores(db):
    cid = db.insert_company(models.Company(name="Acme"))
    p1 = models.JobPosting(
        company_id=cid, title="A", title_hash="a", url="http://x.com/a"
    )
    p2 = models.JobPosting(
        company_id=cid, title="B", title_hash="b", url="http://x.com/b"
    )
    db.insert_posting(p1)
    db.insert_posting(p2)

    results = db.get_postings_with_scores(limit=10)
    assert len(results) == 2
    assert results[0]["company_name"] == "Acme"


def test_get_postings_with_scores_status_new_defaults(db):
    """Postings with no explicit status row should appear as 'new'."""
    cid = db.insert_company(models.Company(name="Acme"))
    posting = models.JobPosting(
        company_id=cid, title="E", title_hash="h", url="http://x.com"
    )
    db.insert_posting(posting)

    # Not yet seen by any user — should appear as "new"
    results = db.get_postings_with_scores(status="new")
    assert len(results) == 1

    # After marking as seen, should not appear as "new"
    pid = results[0]["id"]
    db.update_posting_status(pid, "seen")
    results = db.get_postings_with_scores(status="new")
    assert len(results) == 0

    # Should appear as "seen"
    results = db.get_postings_with_scores(status="seen")
    assert len(results) == 1


def test_get_postings_with_scores_includes_similarity(db):
    cid = db.insert_company(models.Company(name="Acme"))
    posting = models.JobPosting(
        company_id=cid, title="E", title_hash="h", url="http://x.com"
    )
    pid = db.insert_posting(posting)
    db.update_posting_similarity(pid, 0.9)

    results = db.get_postings_with_scores(status="new")
    assert len(results) == 1
    assert results[0]["title"] == "E"
    assert results[0]["similarity_score"] == 0.9


def test_get_postings_for_search(db):
    cid = db.insert_company(models.Company(name="Acme"))
    posting = models.JobPosting(
        company_id=cid, title="E", title_hash="h", url="http://x.com"
    )
    pid = db.insert_posting(posting)
    db.update_posting_embedding(pid, b"emb")

    results = db.get_postings_for_search()
    assert len(results) == 1
    p, name = results[0]
    assert name == "Acme"
    assert p.title == "E"


# ── Label CRUD ─────────────────────────────────────────────────


def test_insert_and_get_label(db):
    cid = db.insert_company(models.Company(name="Acme"))
    posting = models.JobPosting(
        company_id=cid, title="E", title_hash="h", url="http://x.com"
    )
    pid = db.insert_posting(posting)

    label = models.UserLabel(
        user_id=1, posting_id=pid, signal="positive", notes="great fit"
    )
    lid = db.insert_label(label)
    assert lid > 0

    labels = db.get_labels_for_posting(pid)
    assert len(labels) == 1
    assert labels[0].signal == "positive"
    assert labels[0].notes == "great fit"


def test_get_labels_for_posting_user_isolation(db, db_path):
    cid = db.insert_company(models.Company(name="Acme"))
    posting = models.JobPosting(
        company_id=cid, title="E", title_hash="h", url="http://x.com"
    )
    pid = db.insert_posting(posting)

    db.insert_label(models.UserLabel(user_id=1, posting_id=pid, signal="positive"))

    # Insert label for user 2 via raw sqlite3 (FK off by default)
    conn = _raw(db_path)
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (2, 'u2@b.com')")
    conn.execute(
        "INSERT INTO user_labels (user_id, posting_id, signal) VALUES (2, ?, 'negative')",
        (pid,),
    )
    conn.commit()
    conn.close()

    labels = db.get_labels_for_posting(pid, user_id=1)
    assert len(labels) == 1
    assert labels[0].signal == "positive"


# ── System methods ─────────────────────────────────────────────


def test_get_company_name(db):
    cid = db.insert_company(models.Company(name="Acme"))
    assert db.get_company_name(cid) == "Acme"
    assert db.get_company_name(999) is None


def test_insert_crawl_run(db):
    cid = db.insert_company(models.Company(name="Acme"))
    run = models.CrawlRun(
        company_id=cid, status="success", postings_found=5, postings_new=3
    )
    rid = db.insert_crawl_run(run)
    assert rid > 0


def test_insert_agent_action(db):
    action = models.AgentAction(tool_name="test", tool_args="{}")
    aid = db.insert_agent_action(action)
    assert aid > 0


def test_get_agent_actions(db):
    db.insert_agent_action(models.AgentAction(tool_name="t1"))
    db.insert_agent_action(models.AgentAction(tool_name="t2"))
    actions = db.get_agent_actions()
    assert len(actions) == 2
    actions_limited = db.get_agent_actions(limit=1)
    assert len(actions_limited) == 1


def test_insert_and_get_search_queries(db):
    q = models.UserSearchQuery(user_id=1, query_text="senior engineer")
    qid = db.insert_search_query(q)
    assert qid > 0

    queries = db.get_active_search_queries()
    assert len(queries) == 1
    assert queries[0].query_text == "senior engineer"


def test_get_active_search_queries_user_isolation(db, db_path):
    db.insert_search_query(models.UserSearchQuery(user_id=1, query_text="q1"))

    conn = _raw(db_path)
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES (2, 'u2@c.com')")
    conn.execute(
        "INSERT INTO user_search_queries (user_id, query_text) VALUES (2, 'q2')"
    )
    conn.commit()
    conn.close()

    queries = db.get_active_search_queries(user_id=1)
    assert len(queries) == 1
    assert queries[0].query_text == "q1"


def test_get_or_create_location(db):
    parsed = models.ParsedLocation(canonical_name="San Francisco, CA, US")
    loc_id = db.get_or_create_location(parsed)
    assert loc_id > 0

    # Idempotent
    loc_id2 = db.get_or_create_location(parsed)
    assert loc_id == loc_id2


def test_link_posting_location(db, db_path):
    cid = db.insert_company(models.Company(name="Acme"))
    posting = models.JobPosting(
        company_id=cid, title="E", title_hash="h", url="http://x.com"
    )
    pid = db.insert_posting(posting)
    parsed = models.ParsedLocation(canonical_name="SF")
    loc_id = db.get_or_create_location(parsed)

    db.link_posting_location(pid, loc_id)
    # Idempotent
    db.link_posting_location(pid, loc_id)

    conn = _raw(db_path)
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM job_posting_locations WHERE posting_id = ?",
        (pid,),
    ).fetchone()
    conn.close()
    assert row["cnt"] == 1


def test_get_setting_and_set_setting(db):
    assert db.get_setting("nonexistent") is None
    db.set_setting("test_key", "test_value")
    assert db.get_setting("test_key") == "test_value"
    # Overwrite
    db.set_setting("test_key", "new_value")
    assert db.get_setting("test_key") == "new_value"
