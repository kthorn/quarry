"""Tests for quarry.rank.train."""

from contextlib import contextmanager
from unittest import mock

import numpy as np
import pytest

from quarry.rank.train import train_classifier


@pytest.fixture(autouse=True)
def _patch_embedding_dim():
    """Avoid loading the real sentence-transformer model in train/classifier."""
    with (
        mock.patch("quarry.rank.train.get_embedding_dim", return_value=2),
        mock.patch("quarry.rank.scorers.classifier._get_embedding_dim", return_value=2),
    ):
        yield


def _make_rows(positive: int, negative: int) -> list:
    rows = []
    posting_id = 1
    for _ in range(positive):
        rows.append((True, b"emb", posting_id))
        posting_id += 1
    for _ in range(negative):
        rows.append((False, b"emb", posting_id))
        posting_id += 1
    return rows


class _MockSession:
    def add(self, obj):
        obj.id = 1

    def flush(self):
        pass

    def execute(self, stmt):
        pass


@contextmanager
def _mock_session_scope(*args, **kwargs):
    yield _MockSession()


def _training_db_mock(rows: list) -> mock.Mock:
    db = mock.Mock()
    db.engine = mock.Mock()
    db.get_labels_with_postings.return_value = rows
    db.get_all_postings_with_embeddings.return_value = []
    db.insert_pipeline_config.return_value = 1
    db.get_similarity_score.return_value = 0.0
    return db


def test_train_classifier_reports_single_class():
    db = _training_db_mock(_make_rows(0, 5))

    with mock.patch(
        "quarry.rank.train.deserialize_embedding",
        return_value=np.array([1.0, 1.0], dtype=np.float32),
    ):
        result = train_classifier(db, user_id=1, min_labels=5)

    assert "error" in result
    assert "All 5 labels are not-interested" in result["error"]
    assert "both interested and not-interested" in result["error"]
    assert result["training_samples"] == 5


def test_train_classifier_reports_class_imbalance():
    # 1 positive, 4 negative = total 5 (passes min_labels) but minority class = 1
    db = _training_db_mock(_make_rows(1, 4))

    with mock.patch(
        "quarry.rank.train.deserialize_embedding",
        return_value=np.array([1.0, 1.0], dtype=np.float32),
    ):
        result = train_classifier(db, user_id=1, min_labels=5)

    assert "error" in result
    assert "1 interested" in result["error"]
    assert "4 not-interested" in result["error"]
    assert "at least 2 of each class" in result["error"]
    assert result["training_samples"] == 5


def test_train_classifier_succeeds_with_balanced_labels():
    db = _training_db_mock(_make_rows(3, 3))

    np.random.seed(42)

    counter = [0]

    def _deserialize(data, dim):
        # Deterministic embeddings: positive near [1,1], negative near [-1,-1]
        # We can't tell which row from data alone, so alternate based on counter.
        counter[0] += 1
        if counter[0] <= 3:
            return (
                np.array([1.0, 1.0], dtype=np.float32)
                + np.random.randn(2).astype(np.float32) * 0.05
            )
        return (
            np.array([-1.0, -1.0], dtype=np.float32)
            + np.random.randn(2).astype(np.float32) * 0.05
        )

    with (
        mock.patch(
            "quarry.rank.train.deserialize_embedding",
            side_effect=_deserialize,
        ),
        mock.patch("quarry.rank.train.session_scope", _mock_session_scope),
    ):
        result = train_classifier(db, user_id=1, min_labels=5)

    assert "error" not in result
    assert result["training_samples"] == 6
    db.save_user_setting.assert_called()
