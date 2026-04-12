import sqlite3

from quarry.models import Company, JobPosting, ParsedLocation
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


def test_posting_exists_by_url_returns_true_when_exists(tmp_path):
    db_path = tmp_path / "test.db"
    db = init_db(db_path)

    company = Company(name="Test Corp")
    db.insert_company(company)

    posting = JobPosting(
        company_id=1,
        title="Software Engineer",
        title_hash="abc123",
        url="https://example.com/job/123",
        status="new",
    )
    db.insert_posting(posting)

    exists = db.posting_exists_by_url("https://example.com/job/123")
    assert exists is True


def test_posting_exists_by_url_matches_exact_url(tmp_path):
    db_path = tmp_path / "test.db"
    db = init_db(db_path)

    company = Company(name="Test Corp")
    db.insert_company(company)

    posting = JobPosting(
        company_id=1,
        title="Engineer",
        title_hash="hash",
        url="https://example.com/job/123",
        status="new",
    )
    db.insert_posting(posting)

    exists = db.posting_exists_by_url("https://example.com/job/123")
    assert exists is True

    exists = db.posting_exists_by_url("https://example.com/job/456")
    assert exists is False


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


def test_locations_table_exists(tmp_path):
    init_db(tmp_path / "test.db")
    conn = sqlite3.connect(tmp_path / "test.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    assert "locations" in tables
    assert "job_posting_locations" in tables


def test_job_postings_has_work_model(tmp_path):
    init_db(tmp_path / "test.db")
    conn = sqlite3.connect(tmp_path / "test.db")
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(job_postings)")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()
    assert "work_model" in columns
    assert "remote" not in columns


def test_get_or_create_location_inserts_new(tmp_path):
    db = init_db(tmp_path / "test.db")
    parsed = ParsedLocation(
        canonical_name="San Francisco, CA",
        city="San Francisco",
        state="California",
        state_code="CA",
        country="United States",
        country_code="US",
        region="US-West",
    )
    loc_id = db.get_or_create_location(parsed)
    assert loc_id > 0


def test_get_or_create_location_idempotent(tmp_path):
    db = init_db(tmp_path / "test.db")
    parsed = ParsedLocation(
        canonical_name="San Francisco, CA",
        city="San Francisco",
        state="California",
        state_code="CA",
        country="United States",
        country_code="US",
        region="US-West",
    )
    id1 = db.get_or_create_location(parsed)
    id2 = db.get_or_create_location(parsed)
    assert id1 == id2


def test_link_posting_location(tmp_path):
    db = init_db(tmp_path / "test.db")
    company = Company(name="TestCorp")
    cid = db.insert_company(company)
    posting = JobPosting(
        company_id=cid,
        title="Eng",
        title_hash="loc_h1",
        url="https://example.com/loc1",
        work_model="remote",
    )
    pid = db.insert_posting(posting)
    loc = ParsedLocation(canonical_name="Remote", country_code="US", region="US-West")
    lid = db.get_or_create_location(loc)
    db.link_posting_location(pid, lid)

    postings = db.get_postings_by_work_model("remote")
    assert len(postings) >= 1


def test_get_postings_by_location(tmp_path):
    db = init_db(tmp_path / "test.db")
    company = Company(name="TestCorp")
    cid = db.insert_company(company)
    posting = JobPosting(
        company_id=cid,
        title="Eng",
        title_hash="loc_h2",
        url="https://example.com/loc2",
        location="San Francisco, CA",
    )
    pid = db.insert_posting(posting)
    loc = ParsedLocation(
        canonical_name="San Francisco, CA",
        city="San Francisco",
        state_code="CA",
        country_code="US",
        region="US-West",
    )
    lid = db.get_or_create_location(loc)
    db.link_posting_location(pid, lid)

    results = db.get_postings_by_location("San Francisco, CA")
    assert len(results) == 1
    assert results[0].title == "Eng"


def test_get_postings_by_region(tmp_path):
    db = init_db(tmp_path / "test.db")
    company = Company(name="TestCorp")
    cid = db.insert_company(company)
    posting = JobPosting(
        company_id=cid,
        title="Eng",
        title_hash="loc_h3",
        url="https://example.com/loc3",
        location="SF",
    )
    pid = db.insert_posting(posting)
    loc = ParsedLocation(
        canonical_name="San Francisco, CA",
        city="San Francisco",
        state_code="CA",
        country_code="US",
        region="US-West",
    )
    lid = db.get_or_create_location(loc)
    db.link_posting_location(pid, lid)

    results = db.get_postings_by_region("US-West")
    assert len(results) >= 1


def test_get_recent_postings_with_threshold(tmp_path):
    """Postings below threshold are filtered out at read time."""
    db = init_db(tmp_path / "test.db")
    company = Company(name="TestCorp")
    cid = db.insert_company(company)

    for i, score in enumerate([0.8, 0.5, 0.2]):
        posting = JobPosting(
            company_id=cid,
            title=f"Job {i}",
            title_hash=f"hash_thresh_{i}",
            url=f"https://example.com/thresh_{i}",
            similarity_score=score,
        )
        db.insert_posting(posting)

    results = db.get_recent_postings(threshold=0.5)
    for p in results:
        assert p.similarity_score >= 0.5
