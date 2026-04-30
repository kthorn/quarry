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

from quarry.store.db import init_db

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
