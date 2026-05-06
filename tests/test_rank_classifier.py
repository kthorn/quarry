"""Tests for ClassifierScorer: cold-start, training, scoring."""

from types import SimpleNamespace
from unittest import mock

import numpy as np
import pytest

from quarry.rank.context import PipelineContext
from quarry.rank.scorers.classifier import ClassifierScorer


@pytest.fixture(autouse=True)
def _patch_embedding_dim():
    """Patch embedding dim to 2 so synthetic test data matches."""
    with mock.patch(
        "quarry.rank.scorers.classifier._get_embedding_dim", return_value=2
    ):
        yield


def make_label(signal: str, posting_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(signal=signal, posting_id=posting_id)


def make_posting(embedding: np.ndarray, posting_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(embedding=embedding.tobytes(), id=posting_id)


class TestClassifierColdStart:
    def test_not_trained_returns_zero(self):
        scorer = ClassifierScorer(min_training_labels=20)
        ctx = PipelineContext()
        result = scorer.score(1, ctx)
        assert result == 0.0

    def test_is_trained_false_initially(self):
        scorer = ClassifierScorer()
        assert scorer.is_trained is False

    def test_returns_zero_without_db(self):
        scorer = ClassifierScorer()
        scorer._model = object()  # Pretend trained
        ctx = PipelineContext()
        result = scorer.score(1, ctx)
        assert result == 0.0


class TestClassifierFit:
    def make_balanced_labels(self, n_per_class: int = 30) -> tuple[list, list]:
        """Create synthetic balanced labels with separable embeddings."""
        np.random.seed(42)
        labels = []
        postings = []
        for i in range(n_per_class):
            # Positive: centered at [1, 1]
            labels.append(make_label("positive", posting_id=i))
            emb = np.array([1.0, 1.0]) + np.random.randn(2) * 0.1
            postings.append(make_posting(emb.astype(np.float32), posting_id=i))
        for i in range(n_per_class):
            # Negative: centered at [-1, -1]
            labels.append(make_label("negative", posting_id=n_per_class + i))
            emb = np.array([-1.0, -1.0]) + np.random.randn(2) * 0.1
            postings.append(
                make_posting(emb.astype(np.float32), posting_id=n_per_class + i)
            )
        return labels, postings

    def test_fit_with_balanced_labels(self):
        scorer = ClassifierScorer(min_training_labels=20)
        labels, postings = self.make_balanced_labels(30)
        metrics = scorer.fit(labels, postings)
        assert metrics is not None
        assert metrics["training_samples"] == 60
        assert metrics["positive_samples"] == 30
        assert metrics["negative_samples"] == 30
        assert 0.5 < metrics["cv_auc_mean"] <= 1.0

    def test_fit_insufficient_labels(self):
        scorer = ClassifierScorer(min_training_labels=20)
        labels = [make_label("positive", i) for i in range(5)]
        postings = [make_posting(np.ones(2, dtype=np.float32), i) for i in range(5)]
        metrics = scorer.fit(labels, postings)
        assert metrics is None

    def test_fit_skips_missing_embeddings(self):
        scorer = ClassifierScorer(min_training_labels=20)
        np.random.seed(42)
        # 25 positive, 25 negative labels — but only first 25 have embeddings
        labels = [make_label("positive", i) for i in range(25)]
        labels += [make_label("negative", i) for i in range(25, 50)]
        postings = [
            make_posting(
                (
                    np.array([1.0, 1.0]) + np.random.randn(2).astype(np.float32) * 0.1
                ).astype(np.float32),
                i,
            )
            for i in range(25)
        ]
        postings += [SimpleNamespace(embedding=None, id=i) for i in range(25, 50)]
        # All 25 embeddings are positive class only — cross_val_score will fail.
        # fit() should catch that and return None gracefully.
        result = scorer.fit(labels, postings)
        assert result is None

    def test_fit_skips_missing_embeddings_balanced(self):
        scorer = ClassifierScorer(min_training_labels=20)
        np.random.seed(42)
        labels = [make_label("positive", i) for i in range(15)]
        labels += [make_label("negative", i) for i in range(15, 30)]
        # Last 20 have None embeddings
        postings = [
            make_posting(
                (
                    np.array([1.0, 1.0]) + np.random.randn(2).astype(np.float32) * 0.1
                ).astype(np.float32),
                i,
            )
            if i < 15
            else make_posting(
                (
                    -np.array([1.0, 1.0]) + np.random.randn(2).astype(np.float32) * 0.1
                ).astype(np.float32),
                i,
            )
            for i in range(30)
        ]
        postings += [SimpleNamespace(embedding=None, id=i) for i in range(30, 50)]
        metrics = scorer.fit(labels, postings)
        assert metrics is not None
        assert metrics["training_samples"] == 30

    def test_training_sets_is_trained(self):
        scorer = ClassifierScorer(min_training_labels=20)
        labels, postings = self.make_balanced_labels(25)
        scorer.fit(labels, postings)
        assert scorer.is_trained is True

    def test_min_training_labels_custom(self):
        scorer = ClassifierScorer(min_training_labels=10)
        np.random.seed(42)
        labels = [make_label("positive", i) for i in range(10)]
        labels += [make_label("negative", i) for i in range(10, 20)]
        postings = [
            make_posting(
                (
                    np.array([1.0, 1.0], dtype=np.float32)
                    + np.random.randn(2).astype(np.float32) * 0.1
                ).astype(np.float32),
                i,
            )
            if i < 10
            else make_posting(
                (
                    np.array([-1.0, -1.0], dtype=np.float32)
                    + np.random.randn(2).astype(np.float32) * 0.1
                ).astype(np.float32),
                i,
            )
            for i in range(20)
        ]
        metrics = scorer.fit(labels, postings)
        assert metrics is not None
        assert metrics["training_samples"] == 20
