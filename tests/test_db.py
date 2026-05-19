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
        "user_posting_state",
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
    conn.execute(
        "INSERT INTO user_posting_state (user_id, posting_id, interest) VALUES (1, 1, 1)"
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
        "user_posting_state",
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
    conn.execute(
        "INSERT INTO user_posting_state (user_id, posting_id, interest) VALUES (1, 1, 1)"
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
        "user_posting_state",
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
        "idx_state_user",
        "idx_state_posting",
        "idx_state_interest",
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


def test_insert_posting(db, db_path):
    """Inserting a posting creates a row in job_postings."""
    import sqlite3

    company = models.Company(name="AcmeCorp")
    cid = db.insert_company(company)
    pid = db.insert_posting(
        models.JobPosting(
            company_id=cid,
            title="Engineer",
            title_hash="abc",
            url="http://x.com",
        )
    )
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    count = conn.execute(
        "SELECT COUNT(*) FROM job_postings WHERE id = ?", (pid,)
    ).fetchone()[0]
    assert count == 1
    conn.close()


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


def test_get_postings_with_scores_default(db):
    """get_postings_with_scores returns postings."""
    company = models.Company(name="Acme")
    cid = db.insert_company(company)
    db.insert_posting(
        models.JobPosting(
            company_id=cid,
            title="Engineer",
            title_hash="gpws_1",
            url="https://x.com/gpws_1",
        )
    )
    results = db.get_postings_with_scores()
    assert len(results) >= 1
    assert results[0]["title"] == "Engineer"
    assert results[0]["interest"] is None


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


# ── get_postings_with_scores search parameter ───────────────────


class TestGetPostingsWithScores:
    def test_search_by_title(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = models.Company(name="TestCorp")
        cid = db.insert_company(company)
        db.insert_posting(
            models.JobPosting(
                company_id=cid,
                title="Senior Engineer",
                title_hash="srch1",
                url="https://example.com/srch1",
            )
        )
        db.insert_posting(
            models.JobPosting(
                company_id=cid,
                title="Product Manager",
                title_hash="srch2",
                url="https://example.com/srch2",
            )
        )
        results = db.get_postings_with_scores(search="engineer")
        assert len(results) == 1
        assert results[0]["title"] == "Senior Engineer"

    def test_search_by_description(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = models.Company(name="TestCorp")
        cid = db.insert_company(company)
        db.insert_posting(
            models.JobPosting(
                company_id=cid,
                title="Role A",
                title_hash="srch3",
                url="https://example.com/srch3",
                description="Build data pipelines using Python",
            )
        )
        db.insert_posting(
            models.JobPosting(
                company_id=cid,
                title="Role B",
                title_hash="srch4",
                url="https://example.com/srch4",
                description="Manage product roadmap",
            )
        )
        results = db.get_postings_with_scores(search="python")
        assert len(results) == 1
        assert results[0]["title"] == "Role A"

    def test_search_case_insensitive(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = models.Company(name="TestCorp")
        cid = db.insert_company(company)
        db.insert_posting(
            models.JobPosting(
                company_id=cid,
                title="SENIOR ENGINEER",
                title_hash="srch5",
                url="https://example.com/srch5",
            )
        )
        results = db.get_postings_with_scores(search="engineer")
        assert len(results) == 1

    def test_search_no_results(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = models.Company(name="TestCorp")
        cid = db.insert_company(company)
        db.insert_posting(
            models.JobPosting(
                company_id=cid,
                title="Engineer",
                title_hash="srch6",
                url="https://example.com/srch6",
            )
        )
        results = db.get_postings_with_scores(search="zookeeper")
        assert len(results) == 0

    def test_search_special_characters(self, tmp_path):
        """LIKE wildcards % and _ in search terms should be escaped."""
        db = init_db(tmp_path / "test.db")
        company = models.Company(name="Acme Corp")
        cid = db.insert_company(company)
        db.insert_posting(
            models.JobPosting(
                company_id=cid,
                title="100% Remote",
                title_hash="srch9",
                url="https://example.com/srch9",
            )
        )
        db.insert_posting(
            models.JobPosting(
                company_id=cid,
                title="Senior Engineer",
                title_hash="srch10",
                url="https://example.com/srch10",
            )
        )
        # Searching for "100%" should match only "100% Remote", not everything
        results = db.get_postings_with_scores(search="100%")
        assert len(results) == 1
        assert results[0]["title"] == "100% Remote"

    def test_search_empty_string_no_filter(self, tmp_path):
        """Empty search string should return all postings (no filter)."""
        db = init_db(tmp_path / "test.db")
        company = models.Company(name="TestCorp")
        cid = db.insert_company(company)
        db.insert_posting(
            models.JobPosting(
                company_id=cid,
                title="Engineer",
                title_hash="srch11",
                url="https://example.com/srch11",
            )
        )
        db.insert_posting(
            models.JobPosting(
                company_id=cid,
                title="Manager",
                title_hash="srch12",
                url="https://example.com/srch12",
            )
        )
        results = db.get_postings_with_scores(search="")
        assert len(results) == 2

    def test_search_none_no_filter(self, tmp_path):
        """None search should return all postings (backward compatible)."""
        db = init_db(tmp_path / "test.db")
        company = models.Company(name="TestCorp")
        cid = db.insert_company(company)
        db.insert_posting(
            models.JobPosting(
                company_id=cid,
                title="Engineer",
                title_hash="srch13",
                url="https://example.com/srch13",
            )
        )
        results = db.get_postings_with_scores(search=None)
        assert len(results) == 1


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


def test_get_watchlist_companies_filters_discovered(db):
    from quarry.models import Company, UserWatchlistItem

    # Create two companies, one seed (active), one search (inactive)
    c1 = Company(name="SeedCo")
    c2 = Company(name="SearchCo")
    c1.id = db.insert_company(c1)
    c2.id = db.insert_company(c2)

    # Override insert_company defaults: SeedCo stays active/seed
    db.upsert_watchlist_item(
        UserWatchlistItem(user_id=1, company_id=c1.id, active=True, added_reason="seed")
    )
    db.upsert_watchlist_item(
        UserWatchlistItem(
            user_id=1, company_id=c2.id, active=False, added_reason="search"
        )
    )

    # Active only
    active = db.get_watchlist_companies(user_id=1, active=True)
    assert len(active) == 1
    assert active[0]["name"] == "SeedCo"

    # Inactive search-discovered only
    discovered = db.get_watchlist_companies(
        user_id=1, active=False, added_reason="search"
    )
    assert len(discovered) == 1
    assert discovered[0]["name"] == "SearchCo"


class TestGetUserSetting:
    def test_returns_existing_value(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        db.save_user_setting(1, "labels_since_last_train", "42")
        assert db.get_user_setting(1, "labels_since_last_train") == "42"

    def test_returns_none_for_missing_key(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        assert db.get_user_setting(1, "nonexistent") is None

    def test_returns_none_for_null_value(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        # Insert a setting with NULL value directly
        import sqlite3

        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.execute(
            "INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, NULL)",
            (1, "test_key"),
        )
        conn.commit()
        conn.close()
        assert db.get_user_setting(1, "test_key") is None

    def test_preserves_empty_string(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        db.save_user_setting(1, "test_key", "")
        assert db.get_user_setting(1, "test_key") == ""


class TestInsertPipelineConfig:
    def test_insert_new_config(self, db):
        from quarry.rank.config import RankingConfig, StepConfig

        config = RankingConfig(
            steps=[
                StepConfig(
                    step_type="scorer", name="similarity", params={}, enabled=True
                ),
                StepConfig(
                    step_type="scorer", name="classifier", params={}, enabled=True
                ),
            ],
            final_scorer_name="classifier",
        )
        pc_id = db.insert_pipeline_config(1, config, description="classifier v1")
        assert pc_id is not None
        active = db.get_active_pipeline_config(1)
        assert active is not None
        assert active.id == pc_id

    def test_reuses_existing_config_on_duplicate(self, db):
        from quarry.rank.config import RankingConfig, StepConfig

        config = RankingConfig(
            steps=[
                StepConfig(
                    step_type="scorer", name="similarity", params={}, enabled=True
                ),
                StepConfig(
                    step_type="scorer", name="classifier", params={}, enabled=True
                ),
            ],
            final_scorer_name="classifier",
        )
        pc_id1 = db.insert_pipeline_config(1, config, description="classifier v1")
        pc_id2 = db.insert_pipeline_config(1, config, description="classifier v2")
        assert pc_id1 == pc_id2
        # Verify description was updated on the row
        import sqlite3

        conn = sqlite3.connect(str(db.engine.url).replace("sqlite:///", ""))
        row = conn.execute(
            "SELECT description FROM pipeline_configs WHERE id = ?", (pc_id1,)
        ).fetchone()
        conn.close()
        assert row[0] == "classifier v2"

    def test_different_users_can_have_same_config(self, db):
        from quarry.rank.config import RankingConfig, StepConfig

        config = RankingConfig(
            steps=[
                StepConfig(
                    step_type="scorer", name="similarity", params={}, enabled=True
                ),
            ],
            final_scorer_name="similarity",
        )
        # Add a second user
        import sqlite3

        conn = sqlite3.connect(str(db.engine.url).replace("sqlite:///", ""))
        conn.execute(
            "INSERT INTO users (id, email) VALUES (?, ?)", (2, "user2@example.com")
        )
        conn.commit()
        conn.close()

        pc_id1 = db.insert_pipeline_config(1, config, description="user1 config")
        pc_id2 = db.insert_pipeline_config(2, config, description="user2 config")
        assert pc_id1 != pc_id2
        assert db.get_active_pipeline_config(1).id == pc_id1
        assert db.get_active_pipeline_config(2).id == pc_id2


# ── Search query methods ───────────────────────────────────────


class TestSearchQueryMethods:
    """Tests for insert/active/deactivate/get_all search query DB methods."""

    def test_deactivate_search_query(self, db):
        """Deactivating a search query sets active=False."""
        q = models.UserSearchQuery(
            user_id=1, query_text="python developer", active=True
        )
        q_id = db.insert_search_query(q)

        db.deactivate_search_query(q_id)

        queries = db.get_active_search_queries()
        assert len(queries) == 0

    def test_deactivate_search_query_with_retired_reason(self, db):
        """Deactivating with a retired_reason stores the reason."""
        q = models.UserSearchQuery(user_id=1, query_text="java developer", active=True)
        q_id = db.insert_search_query(q)

        db.deactivate_search_query(q_id, retired_reason="no longer needed")

        all_queries = db.get_all_search_queries()
        deactivated = [qq for qq in all_queries if qq.id == q_id]
        assert len(deactivated) == 1
        assert deactivated[0].active is False
        assert deactivated[0].retired_reason == "no longer needed"

    def test_deactivate_search_query_user_isolation(self, db):
        """Cannot deactivate another user's search query."""
        import sqlite3

        conn = sqlite3.connect(str(db.engine.url).replace("sqlite:///", ""))
        conn.execute(
            "INSERT INTO users (id, email) VALUES (?, ?)", (2, "user2@example.com")
        )
        # Insert directly for user 2
        conn.execute(
            "INSERT INTO user_search_queries (user_id, query_text) VALUES (2, 'rust developer')"
        )
        q2_id = conn.execute(
            "SELECT id FROM user_search_queries WHERE user_id=2"
        ).fetchone()[0]
        conn.commit()
        conn.close()

        # Attempt to deactivate from user 1 context — should be a no-op
        db.deactivate_search_query(q2_id)

        # Query should still be active — open a second connection to check
        import sqlite3 as sqlite3_mod

        conn2 = sqlite3_mod.connect(str(db.engine.url).replace("sqlite:///", ""))
        row = conn2.execute(
            "SELECT active FROM user_search_queries WHERE id=?", (q2_id,)
        ).fetchone()
        conn2.close()
        assert row is not None
        assert row[0] == 1, "user 2's query should still be active"

        queries = db.get_active_search_queries(user_id=2)
        assert len(queries) == 1
        assert queries[0].id == q2_id
        assert queries[0].active is True

    def test_get_all_search_queries_returns_active_and_retired(self, db):
        """get_all_search_queries returns both active and inactive queries."""
        q1 = models.UserSearchQuery(user_id=1, query_text="data scientist", active=True)
        q2 = models.UserSearchQuery(user_id=1, query_text="ml engineer", active=True)
        q1_id = db.insert_search_query(q1)
        q2_id = db.insert_search_query(q2)
        db.deactivate_search_query(q1_id)

        all_queries = db.get_all_search_queries()
        ids = {q.id for q in all_queries}
        assert q1_id in ids
        assert q2_id in ids

    def test_get_all_search_queries_ordering(self, db):
        """get_all_search_queries orders by created_at descending."""
        import sqlite3

        # Insert queries directly with explicit created_at timestamps
        conn = sqlite3.connect(str(db.engine.url).replace("sqlite:///", ""))
        conn.execute(
            "INSERT INTO user_search_queries (user_id, query_text, created_at) "
            "VALUES (1, 'oldest query', '2024-01-01 00:00:00')"
        )
        q1_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO user_search_queries (user_id, query_text, created_at) "
            "VALUES (1, 'middle query', '2024-06-01 00:00:00')"
        )
        q2_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO user_search_queries (user_id, query_text, created_at) "
            "VALUES (1, 'newest query', '2024-12-01 00:00:00')"
        )
        q3_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        all_queries = db.get_all_search_queries()
        ids = [q.id for q in all_queries]
        # Most recent first: q3 (2024-12), q2 (2024-06), q1 (2024-01)
        assert ids.index(q3_id) < ids.index(q2_id) < ids.index(q1_id)

    def test_get_all_search_queries_user_isolation(self, db):
        """get_all_search_queries only returns queries for the specified user."""
        import sqlite3

        conn = sqlite3.connect(str(db.engine.url).replace("sqlite:///", ""))
        conn.execute(
            "INSERT INTO users (id, email) VALUES (?, ?)", (2, "user2@example.com")
        )
        conn.execute(
            "INSERT INTO user_search_queries (user_id, query_text) VALUES (2, 'backend engineer')"
        )
        conn.commit()
        conn.close()

        q = models.UserSearchQuery(
            user_id=1, query_text="frontend engineer", active=True
        )
        db.insert_search_query(q)

        user1_queries = db.get_all_search_queries(user_id=1)
        user2_queries = db.get_all_search_queries(user_id=2)

        assert len(user1_queries) == 1
        assert len(user2_queries) == 1
        assert user1_queries[0].query_text == "frontend engineer"
        assert user2_queries[0].query_text == "backend engineer"


# ── User Posting State methods (set_interest, set_applied) ──────


def _setup_posting(db, db_path, company_name="Acme"):
    """Helper: create a company + posting, return (company_id, posting_id)."""
    cid = db.insert_company(models.Company(name=company_name))
    posting = models.JobPosting(
        company_id=cid, title="Engineer", title_hash="abc123", url="http://x.com/j"
    )
    pid = db.insert_posting(posting)
    return cid, pid


class TestSetInterest:
    def test_set_interest_true(self, db, db_path):
        """set_interest(True) stores interest=True in user_posting_state."""
        _, pid = _setup_posting(db, db_path)
        db.set_interest(pid, True)

        conn = _raw(db_path)
        row = conn.execute(
            "SELECT interest FROM user_posting_state WHERE user_id = 1 AND posting_id = ?",
            (pid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["interest"] == 1

    def test_set_interest_false(self, db, db_path):
        """set_interest(False) stores interest=False in user_posting_state."""
        _, pid = _setup_posting(db, db_path)
        db.set_interest(pid, False)

        conn = _raw(db_path)
        row = conn.execute(
            "SELECT interest FROM user_posting_state WHERE user_id = 1 AND posting_id = ?",
            (pid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["interest"] == 0

    def test_set_interest_none_clears(self, db, db_path):
        """set_interest(None) clears interest (sets to NULL)."""
        _, pid = _setup_posting(db, db_path)
        # First set True
        db.set_interest(pid, True)
        # Then clear
        db.set_interest(pid, None)

        conn = _raw(db_path)
        row = conn.execute(
            "SELECT interest FROM user_posting_state WHERE user_id = 1 AND posting_id = ?",
            (pid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["interest"] is None

    def test_set_interest_updates_labeled_at(self, db, db_path):
        """set_interest always updates labeled_at timestamp."""
        _, pid = _setup_posting(db, db_path)
        db.set_interest(pid, True)

        conn = _raw(db_path)
        row = conn.execute(
            "SELECT labeled_at FROM user_posting_state WHERE user_id = 1 AND posting_id = ?",
            (pid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["labeled_at"] is not None

    def test_set_interest_increments_label_counter(self, db, db_path):
        """Setting interest (True/False) increments labels_since_last_train."""
        _, pid = _setup_posting(db, db_path)
        # Initial counter should default to 0
        assert db.get_user_setting(1, "labels_since_last_train") is None

        db.set_interest(pid, True)
        assert db.get_user_setting(1, "labels_since_last_train") == "1"

        db.set_interest(pid, False)
        assert db.get_user_setting(1, "labels_since_last_train") == "2"

    def test_set_interest_none_does_not_increment_counter(self, db, db_path):
        """Setting interest=None does not count as a label action."""
        _, pid = _setup_posting(db, db_path)
        db.set_interest(pid, True)
        assert db.get_user_setting(1, "labels_since_last_train") == "1"

        # Clearing should NOT increment
        db.set_interest(pid, None)
        assert db.get_user_setting(1, "labels_since_last_train") == "1"

    def test_set_interest_threshold_triggers_retrain(self, db, db_path):
        """When labels_since_last_train reaches threshold, retrain_pending = true."""
        _, pid = _setup_posting(db, db_path)
        # Set threshold to 2
        db.save_user_setting(1, "retrain_label_threshold", "2")

        # First label: count 1, not at threshold
        db.set_interest(pid, True)
        assert db.get_user_setting(1, "retrain_pending") is None

        # set_interest on another posting to increment counter
        pid2 = db.insert_posting(
            models.JobPosting(
                company_id=db.get_posting_by_id(pid).company_id,
                title="Manager",
                title_hash="xyz",
                url="http://x.com/m",
            )
        )
        db.set_interest(pid2, False)
        assert db.get_user_setting(1, "labels_since_last_train") == "2"
        assert db.get_user_setting(1, "retrain_pending") == "true"

    def test_set_interest_idempotent_on_same_posting(self, db, db_path):
        """Repeated interest on same posting still increments counter (upsert)."""
        _, pid = _setup_posting(db, db_path)
        db.set_interest(pid, True)
        assert db.get_user_setting(1, "labels_since_last_train") == "1"

        db.set_interest(pid, False)  # change mind
        assert db.get_user_setting(1, "labels_since_last_train") == "2"


class TestSetApplied:
    def test_set_applied_true(self, db, db_path):
        """set_applied(True) stores applied=1 in user_posting_state."""
        _, pid = _setup_posting(db, db_path)
        db.set_applied(pid, True)

        conn = _raw(db_path)
        row = conn.execute(
            "SELECT applied FROM user_posting_state WHERE user_id = 1 AND posting_id = ?",
            (pid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["applied"] == 1

    def test_set_applied_false(self, db, db_path):
        """set_applied(False) stores applied=0 in user_posting_state."""
        _, pid = _setup_posting(db, db_path)
        db.set_applied(pid, False)

        conn = _raw(db_path)
        row = conn.execute(
            "SELECT applied FROM user_posting_state WHERE user_id = 1 AND posting_id = ?",
            (pid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["applied"] == 0

    def test_set_applied_does_not_increment_label_counter(self, db, db_path):
        """set_applied does not affect labels_since_last_train."""
        _, pid = _setup_posting(db, db_path)
        db.set_applied(pid, True)
        assert db.get_user_setting(1, "labels_since_last_train") is None

    def test_set_interest_and_applied_independent(self, db, db_path):
        """set_interest and set_applied can be set independently on same posting."""
        _, pid = _setup_posting(db, db_path)
        db.set_interest(pid, True)
        db.set_applied(pid, True)

        conn = _raw(db_path)
        row = conn.execute(
            "SELECT interest, applied FROM user_posting_state WHERE user_id = 1 AND posting_id = ?",
            (pid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["interest"] == 1
        assert row["applied"] == 1


class TestGetPostingsWithScoresNew:
    """Tests for the rewritten get_postings_with_scores method."""

    def test_interest_filter_interested(self, db):
        """Interest filter 'interested' returns only interest=True postings."""
        company = models.Company(name="FilterCo")
        cid = db.insert_company(company)
        pid1 = db.insert_posting(
            models.JobPosting(
                company_id=cid,
                title="Good Job",
                title_hash="f1",
                url="https://x.com/f1",
            )
        )
        pid2 = db.insert_posting(
            models.JobPosting(
                company_id=cid, title="Bad Job", title_hash="f2", url="https://x.com/f2"
            )
        )

        db.set_interest(pid1, True)
        db.set_interest(pid2, False)

        results = db.get_postings_with_scores(interest="interested")
        assert len(results) == 1
        assert results[0]["title"] == "Good Job"

    def test_interest_filter_untagged(self, db):
        """Interest filter 'untagged' returns only interest=NULL postings."""
        company = models.Company(name="FilterCo2")
        cid = db.insert_company(company)
        pid1 = db.insert_posting(
            models.JobPosting(
                company_id=cid, title="Tagged", title_hash="f3", url="https://x.com/f3"
            )
        )
        db.insert_posting(
            models.JobPosting(
                company_id=cid,
                title="Untagged",
                title_hash="f4",
                url="https://x.com/f4",
            )
        )

        db.set_interest(pid1, True)

        results = db.get_postings_with_scores(interest="untagged")
        titles = [r["title"] for r in results]
        assert "Untagged" in titles
        assert "Tagged" not in titles
