import pytest

from quarry.digest.digest import build_digest, format_digest, write_digest
from quarry.models import Company, JobPosting
from quarry.store.db import init_db


@pytest.fixture
def db(tmp_path):
    return init_db(tmp_path / "test.db")


@pytest.fixture
def db_with_postings(db):
    company = Company(name="TestCorp", ats_type="greenhouse", ats_slug="testcorp")
    cid = db.insert_company(company)

    for i in range(3):
        posting = JobPosting(
            company_id=cid,
            title=f"Senior Analyst {i}",
            title_hash=f"hash_{i}",
            url=f"https://example.com/job/{i}",
            description=f"Great analytics role {i}",
            location="Remote, US",
            work_model="remote",
            similarity_score=0.8 - i * 0.1,
            source_type="greenhouse",
        )
        db.insert_posting(posting)
    return db


class TestBuildDigest:
    def test_returns_recent_postings(self, db_with_postings):
        entries = build_digest(db_with_postings, limit=10)
        assert len(entries) == 3

    def test_sorted_by_similarity(self, db_with_postings):
        entries = build_digest(db_with_postings, limit=10)
        scores = [e["similarity_score"] for e in entries]
        assert scores == sorted(scores, reverse=True)

    def test_marks_postings_seen(self, db_with_postings):
        entries = build_digest(db_with_postings, limit=10)
        posting_ids = [e["id"] for e in entries]
        db_with_postings.mark_postings_seen(posting_ids)

        new_entries = build_digest(db_with_postings, limit=10)
        assert len(new_entries) == 0


class TestFormatDigest:
    def test_formats_as_plain_text(self, db_with_postings):
        entries = build_digest(db_with_postings, limit=10)
        text = format_digest(entries)
        assert "TestCorp" in text
        assert "Senior Analyst" in text
        assert "score" in text.lower() or "similarity" in text.lower()

    def test_empty_digest(self, db_with_postings):
        text = format_digest([])
        assert "no new" in text.lower() and "postings" in text.lower()


class TestWriteDigest:
    def test_writes_to_file(self, db_with_postings, tmp_path):
        entries = build_digest(db_with_postings, limit=10)
        output_path = tmp_path / "digest.txt"
        write_digest(entries, str(output_path))
        assert output_path.exists()
        content = output_path.read_text()
        assert "Senior Analyst" in content
