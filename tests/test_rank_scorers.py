"""Tests for ranking scorers: similarity, keyword, weighted average."""

import pytest

from quarry.rank.context import PipelineContext
from quarry.rank.scorers.keyword import KeywordHeuristicScorer, _normalize_to_01
from quarry.rank.scorers.similarity import SimilarityScorer


class MockDB:
    """Minimal mock DB for scorers that need database access."""

    def __init__(self, similarity_scores=None):
        self._similarity = similarity_scores or {}

    def get_similarity_score(self, user_id, posting_id):
        return self._similarity.get((user_id, posting_id))

    def get_posting_by_id(self, posting_id):
        # Return a mock posting with title and description
        class MockPosting:
            title = ""
            description = ""

        return MockPosting()


class TestNormalizeTo01:
    def test_zero(self):
        assert _normalize_to_01(0.0) == 0.5

    def test_positive(self):
        assert _normalize_to_01(3.0) > 0.9

    def test_negative(self):
        assert _normalize_to_01(-3.0) < 0.1

    def test_monotonic(self):
        assert _normalize_to_01(5.0) > _normalize_to_01(1.0)


class TestSimilarityScorer:
    def test_returns_stored_score(self):
        db = MockDB({(1, 42): 0.75})
        scorer = SimilarityScorer()
        ctx = PipelineContext()
        ctx.db = db
        ctx.user_id = 1
        result = scorer.score(42, ctx)
        assert result == 0.75

    def test_returns_zero_when_missing(self):
        db = MockDB({})
        scorer = SimilarityScorer()
        ctx = PipelineContext()
        ctx.db = db
        ctx.user_id = 1
        result = scorer.score(99, ctx)
        assert result == 0.0

    def test_returns_zero_without_db(self):
        scorer = SimilarityScorer()
        ctx = PipelineContext()
        result = scorer.score(1, ctx)
        assert result == 0.0


class TestKeywordHeuristicScorer:
    def _make_db(self, title="", description=""):
        db = MockDB()

        class MockPosting:
            pass

        p = MockPosting()
        p.title = title
        p.description = description
        db.get_posting_by_id = lambda pid: p
        return db

    def test_extract_single_match(self):
        scorer = KeywordHeuristicScorer(
            rules=[{"pattern": "python", "field": "title", "weight": 3.0}]
        )
        db = self._make_db(title="Senior Python Developer")
        ctx = PipelineContext()
        ctx.db = db
        features = scorer.extract(1, ctx)
        assert features.get("kw_python") == 1.0

    def test_extract_no_match(self):
        scorer = KeywordHeuristicScorer(
            rules=[{"pattern": "golang", "field": "title", "weight": 3.0}]
        )
        db = self._make_db(title="Senior Python Developer")
        ctx = PipelineContext()
        ctx.db = db
        features = scorer.extract(1, ctx)
        assert features.get("kw_golang") == 0.0

    def test_extract_multiple_rules(self):
        scorer = KeywordHeuristicScorer(
            rules=[
                {"pattern": "senior", "field": "title", "weight": 2.0},
                {"pattern": "python", "field": "title", "weight": 3.0},
            ]
        )
        db = self._make_db(title="Senior Python Developer")
        ctx = PipelineContext()
        ctx.db = db
        features = scorer.extract(1, ctx)
        assert features.get("kw_senior") == 1.0
        assert features.get("kw_python") == 1.0

    def test_extract_description_field(self):
        scorer = KeywordHeuristicScorer(
            rules=[
                {"pattern": "machine learning", "field": "description", "weight": 1.0}
            ]
        )
        db = self._make_db(
            title="Engineer",
            description="Experience with machine learning required.",
        )
        ctx = PipelineContext()
        ctx.db = db
        features = scorer.extract(1, ctx)
        assert features.get("kw_machine learning") == 1.0

    def test_score_with_matches(self):
        scorer = KeywordHeuristicScorer(
            rules=[
                {"pattern": "senior", "field": "title", "weight": 2.0},
                {"pattern": "python", "field": "title", "weight": 3.0},
            ]
        )
        db = self._make_db(title="Senior Python Developer")
        ctx = PipelineContext()
        ctx.db = db
        ctx.features.update(scorer.extract(1, ctx))  # populate features
        score = scorer.score(1, ctx)
        # Both match → raw = 2.0 + 3.0 = 5.0 → sigmoid
        expected = _normalize_to_01(5.0)
        assert score == pytest.approx(expected)

    def test_score_no_matches(self):
        scorer = KeywordHeuristicScorer(
            rules=[{"pattern": "golang", "field": "title", "weight": 5.0}]
        )
        db = self._make_db(title="Python Developer")
        ctx = PipelineContext()
        ctx.db = db
        ctx.features.update(scorer.extract(1, ctx))
        score = scorer.score(1, ctx)
        assert score == _normalize_to_01(0.0)

    def test_default_rules(self):
        scorer = KeywordHeuristicScorer()
        assert scorer.rules == []
