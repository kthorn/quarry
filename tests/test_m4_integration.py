"""Integration tests for the full M4 pipeline: extract → embed → filter → store."""

import numpy as np
import pytest

from quarry.models import RawPosting
from quarry.pipeline.embedder import (
    deserialize_embedding,
    get_ideal_embedding,
    serialize_embedding,
    set_ideal_embedding,
)
from quarry.pipeline.extract import extract
from quarry.pipeline.filter import filter_posting
from quarry.store.db import init_db


@pytest.fixture
def db(tmp_path):
    return init_db(str(tmp_path / "test.db"))


@pytest.fixture
def seed_company(db):
    from quarry.models import Company

    company = Company(name="TestCorp", ats_type="greenhouse", ats_slug="testcorp")
    company_id = db.insert_company(company)
    return company_id


class TestEndToEndPipeline:
    def test_extract_embed_filter_store(self, db, seed_company):
        ideal_desc = "Senior people analytics leader at a growth-stage tech company"
        ideal_emb = set_ideal_embedding(db, ideal_desc)

        raw = RawPosting(
            company_id=seed_company,
            title="Senior People Analytics Manager",
            url="https://example.com/job/1",
            description="Lead the people analytics function at our company",
            location="Remote, US",
            source_type="greenhouse",
        )

        posting, _ = extract(raw)
        assert posting.work_model in ("remote", "hybrid")

        result = filter_posting(raw, ideal_emb, threshold=0.3, blocklist=[])
        assert result.passed is True
        assert result.similarity_score is not None
        assert result.similarity_score > 0.3

        posting.similarity_score = result.similarity_score

        posting_id = db.insert_posting(posting)
        assert posting_id > 0

        db.update_posting_similarity(posting_id, result.similarity_score)

        fetched_postings = db.get_postings(status="new")
        assert len(fetched_postings) >= 1
        fetched = fetched_postings[0]
        assert fetched.similarity_score == result.similarity_score

    def test_blocklisted_posting_rejected(self, db, seed_company):
        ideal_emb = np.ones(384, dtype=np.float32)
        ideal_emb = ideal_emb / np.linalg.norm(ideal_emb)

        raw = RawPosting(
            company_id=seed_company,
            title="Staffing Agency Recruiter",
            url="https://example.com/job/2",
            description="Work at a staffing agency placing candidates",
            source_type="greenhouse",
        )

        result = filter_posting(
            raw, ideal_emb, threshold=0.3, blocklist=["staffing agency"]
        )
        assert result.passed is False
        assert result.skip_reason == "blocklist"

    def test_low_similarity_rejected(self, db, seed_company):
        ideal_emb = np.zeros(384, dtype=np.float32)
        ideal_emb[0] = 1.0

        raw = RawPosting(
            company_id=seed_company,
            title="Line Cook",
            url="https://example.com/job/3",
            description="Prepare food in restaurant kitchen",
            source_type="lever",
        )

        result = filter_posting(raw, ideal_emb, threshold=0.58, blocklist=[])
        assert result.passed is False
        assert result.skip_reason == "low_similarity"

    def test_ideal_embedding_persists(self, db):
        desc = "Senior people analytics or HR technology leader"
        emb = set_ideal_embedding(db, desc)

        retrieved = get_ideal_embedding(db)
        assert retrieved is not None
        assert np.allclose(emb, retrieved)

    def test_embedding_serialization_roundtrip(self):
        emb = np.random.rand(384).astype(np.float32)
        emb = emb / np.linalg.norm(emb)

        serialized = serialize_embedding(emb)
        assert isinstance(serialized, bytes)

        deserialized = deserialize_embedding(serialized)
        assert np.allclose(emb, deserialized)

    def test_store_and_retrieve_embedding(self, db, seed_company):
        emb = np.random.rand(384).astype(np.float32)
        serialized = serialize_embedding(emb)

        from quarry.models import JobPosting

        posting = JobPosting(
            company_id=seed_company,
            title="Test Engineer",
            title_hash="abc123",
            url="https://example.com/job/embed",
            source_type="greenhouse",
            similarity_score=0.75,
            embedding=serialized,
        )

        posting_id = db.insert_posting(posting)
        assert posting_id > 0

        db.update_posting_embedding(posting_id, serialized)

        rows = db.execute(
            "SELECT embedding FROM job_postings WHERE id = ?", (posting_id,)
        )
        assert rows is not None
        stored = rows[0]["embedding"]
        retrieved = deserialize_embedding(stored)
        assert np.allclose(emb, retrieved)

    def test_dedup_prevents_duplicate_insert(self, db, seed_company):
        from quarry.models import JobPosting

        posting = JobPosting(
            company_id=seed_company,
            title="Duplicate Engineer",
            title_hash="hash123",
            url="https://example.com/job/dup",
            source_type="greenhouse",
        )

        db.insert_posting(posting)
        assert db.posting_exists(seed_company, "hash123") is True
        assert db.posting_exists_by_url("https://example.com/job/dup") is True
