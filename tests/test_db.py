import sqlite3
from quarry.store.db import Database, init_db


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
