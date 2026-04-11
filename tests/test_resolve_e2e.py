import sqlite3

from quarry.models import Company
from quarry.store.db import Database, init_db


def test_full_resolve_pipeline_e2e(tmp_path):
    db = init_db(tmp_path / "test_e2e.db")

    company = Company(name="Greenhouse Test Corp")
    company.id = db.insert_company(company)
    assert company.id is not None

    fetched = db.get_company(company.id)
    assert fetched is not None
    assert fetched.resolve_status == "unresolved"
    assert fetched.resolve_attempts == 0

    company.domain = "example.com"
    company.careers_url = "https://boards.greenhouse.io/examplecorp"
    company.ats_type = "greenhouse"
    company.ats_slug = "examplecorp"
    company.resolve_status = "resolved"
    db.update_company(company)

    fetched = db.get_company(company.id)
    assert fetched.resolve_status == "resolved"
    assert fetched.ats_type == "greenhouse"


def test_migrate_existing_resolved_companies(tmp_path):
    db_path = tmp_path / "test_migrate.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE companies (id INTEGER PRIMARY KEY, name TEXT, domain TEXT, "
        "careers_url TEXT, ats_type TEXT DEFAULT 'unknown', ats_slug TEXT, "
        "active BOOLEAN DEFAULT TRUE, crawl_priority INTEGER DEFAULT 5, "
        "notes TEXT, added_by TEXT DEFAULT 'seed', added_reason TEXT, "
        "last_crawled_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO companies (name, domain, careers_url, ats_type, ats_slug) "
        "VALUES ('Resolved Corp', 'resolved.com', 'https://resolved.com/careers', 'greenhouse', 'resolved')"
    )
    conn.execute(
        "INSERT INTO companies (name, ats_type) VALUES ('Unknown Corp', 'unknown')"
    )
    conn.commit()
    conn.close()

    db = Database(db_path)
    db.migrate_resolve_columns()

    resolved = db.get_company_by_name("Resolved Corp")
    assert resolved is not None
    assert resolved.resolve_status == "resolved"

    unknown = db.get_company_by_name("Unknown Corp")
    assert unknown is not None
    assert unknown.resolve_status == "unresolved"
