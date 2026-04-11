"""Tests for embedding pipeline."""

import numpy as np

from quarry.pipeline.embedder import (
    embed_posting,
    embed_text,
    get_embedding_dim,
    get_ideal_embedding,
    set_ideal_embedding,
)


class TestEmbedText:
    def test_returns_ndarray(self):
        result = embed_text("Senior software engineer")
        assert isinstance(result, np.ndarray)

    def test_dimension(self):
        result = embed_text("Senior software engineer")
        assert result.shape == (get_embedding_dim(),)

    def test_normalized(self):
        result = embed_text("Senior software engineer")
        norm = np.linalg.norm(result)
        assert abs(norm - 1.0) < 1e-6

    def test_different_text_differs(self):
        r1 = embed_text("Senior software engineer")
        r2 = embed_text("Head chef at a restaurant")
        cos = np.dot(r1, r2) / (np.linalg.norm(r1) * np.linalg.norm(r2))
        assert cos < 0.9

    def test_similar_text_close(self):
        r1 = embed_text("Senior people analytics leader")
        r2 = embed_text("Director of HR technology")
        cos = np.dot(r1, r2) / (np.linalg.norm(r1) * np.linalg.norm(r2))
        assert cos > 0.3

    def test_empty_string_returns_zeros(self):
        result = embed_text("")
        assert isinstance(result, np.ndarray)
        assert np.allclose(result, np.zeros_like(result))

    def test_deterministic(self):
        r1 = embed_text("Software engineer")
        r2 = embed_text("Software engineer")
        assert np.allclose(r1, r2)


class TestEmbedPosting:
    def test_combines_title_and_description(self):
        from quarry.models import RawPosting

        raw = RawPosting(
            company_id=1,
            title="Senior Data Scientist",
            url="https://example.com/1",
            description="Build ML models for workforce analytics",
            location="Remote",
            source_type="greenhouse",
        )
        result = embed_posting(raw)
        assert isinstance(result, np.ndarray)
        assert result.shape == (get_embedding_dim(),)

    def test_title_only_when_no_description(self):
        from quarry.models import RawPosting

        raw = RawPosting(
            company_id=1,
            title="Software Engineer",
            url="https://example.com/2",
            source_type="lever",
        )
        result = embed_posting(raw)
        assert isinstance(result, np.ndarray)
        assert result.shape == (get_embedding_dim(),)


class TestIdealEmbedding:
    def test_set_and_get(self, tmp_path):
        from quarry.store.db import init_db

        db = init_db(str(tmp_path / "test.db"))
        desc = "Senior people analytics leader at a tech company"
        set_ideal_embedding(db, desc)

        result = get_ideal_embedding(db)
        assert result is not None
        assert isinstance(result, np.ndarray)
        assert result.shape == (get_embedding_dim(),)

    def test_get_returns_none_when_not_set(self, tmp_path):
        from quarry.store.db import init_db

        db = init_db(str(tmp_path / "test2.db"))
        result = get_ideal_embedding(db)
        assert result is None
