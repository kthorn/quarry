"""ClassifierScorer — logistic regression on posting embeddings.

Trained on user labels (positive/negative signals) and stored per-user.
Cold-start returns 0.0 until training with >= min_training_labels labels.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from quarry.rank.base import Scorer
from quarry.rank.registry import register

if TYPE_CHECKING:
    from quarry.rank.context import PipelineContext

log = logging.getLogger(__name__)


def _get_embedding_dim() -> int:
    from quarry.pipeline.embedder import get_embedding_dim as _dim

    return _dim()


def _deserialize_embedding(data: bytes, dim: int) -> np.ndarray:
    from quarry.pipeline.embedder import deserialize_embedding as _deser

    return _deser(data, dim=dim)


def _get_models_dir() -> Path:
    p = Path("quarry/models")
    p.mkdir(parents=True, exist_ok=True)
    return p


@register("classifier")
class ClassifierScorer(Scorer):
    """Logistic regression classifier trained on user labels.

    Params:
        min_training_labels: Minimum labels required before training (default 20).
    """

    name: str = "classifier"

    def __init__(self, min_training_labels: int = 20) -> None:
        self.min_training_labels = min_training_labels
        self._model = None
        self._model_version_id: int | None = None

    @property
    def is_trained(self) -> bool:
        return self._model is not None

    @property
    def model(self):
        return self._model

    @property
    def model_version_id(self) -> int | None:
        return self._model_version_id

    def fit(
        self,
        labels: list,
        postings: list,
    ) -> dict | None:
        """Train logistic regression on labeled postings.

        Args:
            labels: List of UserLabel ORM rows with signal in ('positive', 'negative').
            postings: List of JobPosting ORM rows (must have .embedding attribute).

        Returns:
            Dict with cv metrics and the trained model, or None if insufficient labels.
        """
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import cross_val_score

        if len(labels) < self.min_training_labels:
            log.warning(
                "Insufficient labels: %d < %d",
                len(labels),
                self.min_training_labels,
            )
            return None

        dim = _get_embedding_dim()

        x_list = []
        y_list = []
        for label, posting in zip(labels, postings):
            if posting.embedding is None:
                continue
            try:
                emb = _deserialize_embedding(posting.embedding, dim)
            except (ValueError, TypeError) as e:
                log.warning("Skipping posting %d: bad embedding: %s", posting.id, e)
                continue
            x_list.append(emb)
            y_list.append(1 if label.signal == "positive" else 0)

        if len(y_list) < self.min_training_labels:
            log.warning(
                "After filtering embeddings: %d < %d",
                len(y_list),
                self.min_training_labels,
            )
            return None

        x_mat = np.vstack(x_list)
        y_vec = np.array(y_list)

        clf = LogisticRegression(max_iter=1000)
        cv = min(5, len(y_list))
        try:
            cv_scores = cross_val_score(clf, x_mat, y_vec, cv=cv, scoring="roc_auc")
        except ValueError as e:
            log.warning("Cross-validation failed (likely single-class): %s", e)
            return None
        clf.fit(x_mat, y_vec)

        self._model = clf

        metrics = {
            "training_samples": len(y_list),
            "positive_samples": int(y_vec.sum()),
            "negative_samples": int(len(y_list) - y_vec.sum()),
            "cv_auc_mean": float(cv_scores.mean()),
            "cv_auc_std": float(cv_scores.std()),
        }
        log.info("Classifier trained: %s", metrics)
        return metrics

    def score(self, posting_id: int, context: "PipelineContext") -> float:
        if self._model is None:
            return 0.0

        db = getattr(context, "db", None)
        if db is None:
            return 0.0

        posting = db.get_posting_by_id(posting_id)
        if posting is None or posting.embedding is None:
            return 0.0

        dim = _get_embedding_dim()
        try:
            emb = _deserialize_embedding(posting.embedding, dim)
        except (ValueError, TypeError):
            return 0.0

        prob = self._model.predict_proba(emb.reshape(1, -1))[0][1]
        return float(prob)
