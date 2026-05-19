"""ClassifierScorer — logistic regression on posting embeddings.

Trained on user labels (positive/negative signals) and stored per-user.
Cold-start returns 0.0 until training with >= min_training_labels labels.
"""

from __future__ import annotations

import logging
import pickle
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from quarry.rank.base import Scorer
from quarry.rank.registry import register

if TYPE_CHECKING:
    from quarry.rank.context import PipelineContext

log = logging.getLogger(__name__)

# Suppress BERT model loading warnings (cosmetic only).
logging.getLogger("transformers.modeling_utils").setLevel(logging.ERROR)


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
            labels: List of booleans (True=interested, False=not interested).
            postings: List of objects with .embedding attribute.

        Returns:
            Dict with cv metrics and the trained model, or None if insufficient labels.
        """

        from sklearn.exceptions import UndefinedMetricWarning
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
            y_list.append(1 if label else 0)

        if len(y_list) < self.min_training_labels:
            log.warning(
                "After filtering embeddings: %d < %d",
                len(y_list),
                self.min_training_labels,
            )
            return None

        x_mat = np.vstack(x_list)
        y_vec = np.array(y_list)

        # Guard: need both classes present for meaningful AUC
        class_counts = np.bincount(y_vec)
        if len(class_counts) < 2:
            log.warning(
                "Only one class present after filtering — cannot train classifier"
            )
            return None

        # Ensure cv doesn't exceed the minority class count
        min_class = class_counts.min()
        cv = min(5, min_class, len(y_list) // 2)
        if cv < 2:
            log.warning(
                "Too few samples per class for cross-validation "
                "(minority class: %d, cv=%d)",
                min_class,
                cv,
            )
            return None

        clf = LogisticRegression(max_iter=1000)
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Only one class is present",
                category=UndefinedMetricWarning,
            )
            cv_scores = cross_val_score(clf, x_mat, y_vec, cv=cv, scoring="roc_auc")

        # Filter out NaN scores from degenerately small folds
        valid = cv_scores[~np.isnan(cv_scores)]
        if len(valid) < 2:
            log.warning(
                "Cross-validation produced only %d valid fold(s) — cannot estimate AUC",
                len(valid),
            )
            return None

        clf.fit(x_mat, y_vec)
        self._model = clf

        metrics = {
            "training_samples": len(y_list),
            "positive_samples": int(y_vec.sum()),
            "negative_samples": int(len(y_list) - y_vec.sum()),
            "cv_auc_mean": float(valid.mean()),
            "cv_auc_std": float(valid.std()),
        }
        log.info("Classifier trained: %s", metrics)
        return metrics

    def _try_load_model(self, db) -> bool:
        """Load the latest active classifier model from disk.

        Returns True if a model was loaded.
        """
        try:
            from sqlalchemy import select

            from quarry.store.models import ClassifierVersion as ORMClsVer
            from quarry.store.session import session_scope

            with session_scope(engine=db.engine) as session:
                version = session.execute(
                    select(ORMClsVer)
                    .where(ORMClsVer.active.is_(True))
                    .order_by(ORMClsVer.id.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if version is None or not version.model_path:
                    return False
                with open(version.model_path, "rb") as f:
                    self._model = pickle.load(f)
                self._model_version_id = version.id
                return True
        except Exception:
            log.warning("Failed to load classifier model", exc_info=True)
            return False

    def score(self, posting_id: int, context: "PipelineContext") -> float:
        if self._model is None:
            db = getattr(context, "db", None)
            if db is None:
                return 0.0
            if not self._try_load_model(db):
                return 0.0
        assert self._model is not None  # narrow for pyright

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
