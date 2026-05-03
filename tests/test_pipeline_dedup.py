"""Tests for deduplication integration."""

from quarry.models import Company, RawPosting
from quarry.pipeline.extract import extract
from quarry.store.db import init_db


def test_duplicate_posting_is_skipped(tmp_path):
    db_path = tmp_path / "test.db"
    db = init_db(db_path)

    # Insert a company
    company = Company(name="Test Corp")
    db.insert_company(company)

    # Create and insert first posting
    raw1 = RawPosting(
        company_id=1,
        title="Software Engineer",
        url="https://example.com/job/123",
        description="Great role",
        source_type="greenhouse",
    )
    posting1, _ = extract(raw1)
    db.insert_posting(posting1)

    # Try to insert duplicate (same URL)
    raw2 = RawPosting(
        company_id=1,
        title="Software Engineer",
        url="https://example.com/job/123",
        description="Great role",
        source_type="greenhouse",
    )
    posting2, _ = extract(raw2)

    # Check if exists before insert
    if not db.posting_exists_by_url(posting2.url):
        db.insert_posting(posting2)

    # Verify only one posting exists
    assert db.posting_exists_by_url("https://example.com/job/123")
    postings = db.get_postings()
    matching = [p for p in postings if p.url == posting2.url]
    assert len(matching) == 1


def test_different_postings_are_both_inserted(tmp_path):
    db_path = tmp_path / "test.db"
    db = init_db(db_path)

    # Insert a company
    company = Company(name="Test Corp")
    db.insert_company(company)

    # Insert first posting
    raw1 = RawPosting(
        company_id=1,
        title="Software Engineer",
        url="https://example.com/job/123",
        source_type="greenhouse",
    )
    posting1, _ = extract(raw1)
    if not db.posting_exists_by_url(posting1.url):
        db.insert_posting(posting1)

    # Insert second posting (different URL)
    raw2 = RawPosting(
        company_id=1,
        title="Senior Engineer",
        url="https://example.com/job/456",
        source_type="greenhouse",
    )
    posting2, _ = extract(raw2)
    if not db.posting_exists_by_url(posting2.url):
        db.insert_posting(posting2)

    # Verify both exist
    assert db.posting_exists_by_url("https://example.com/job/123")
    assert db.posting_exists_by_url("https://example.com/job/456")
    assert db.count_postings() == 2
