"""Classifier training logic shared between CLI and web UI."""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import update

from quarry.pipeline.embedder import deserialize_embedding, get_embedding_dim
from quarry.rank.scorers.classifier import ClassifierScorer
from quarry.store.models import ClassifierVersion as ORMClsVersion
from quarry.store.session import session_scope

log = logging.getLogger(__name__)

# Absolute path to models directory, computed at module level from this file's location.
# __file__ is quarry/rank/train.py → parent.parent is quarry/ → then /models.
_MODELS_DIR = Path(__file__).parent.parent / "models"


def train_classifier(
    db: Any,
    user_id: int = 1,
    min_labels: int = 5,
) -> dict:
    """Train a logistic regression classifier on user labels.

    Args:
        db: Database instance (must have engine, get_labels_with_postings,
            save_user_setting).
        user_id: User whose labels to train on.
        min_labels: Minimum labeled postings required before training begins.

    Returns:
        On success: {training_samples: int, cv_auc_mean: float, model_path: str}
        On failure: {error: str} and optionally {training_samples: int}
    """
    rows = db.get_labels_with_postings(user_id=user_id)
    if not rows:
        return {
            "error": "No labeled postings found. Label some postings first.",
            "training_samples": 0,
        }

    dim = get_embedding_dim()
    valid_labels = []
    embeddings = []

    for row in rows:
        label, emb_bytes, posting_id = row
        if emb_bytes is None:
            continue
        try:
            emb = deserialize_embedding(emb_bytes, dim)
        except (ValueError, TypeError):
            continue
        posting = SimpleNamespace(embedding=emb, id=posting_id)
        embeddings.append(posting)
        valid_labels.append(label)

    if len(valid_labels) < min_labels:
        return {
            "error": (
                f"Not enough labeled postings ({len(valid_labels)} < {min_labels}). "
                "Label more postings first."
            ),
            "training_samples": len(valid_labels),
        }

    scorer = ClassifierScorer(min_training_labels=min_labels)
    result = scorer.fit(valid_labels, embeddings)
    if result is None:
        return {
            "error": (
                "Training failed — insufficient labels after filtering embeddings."
            ),
            "training_samples": len(valid_labels),
        }

    # Persist ClassifierVersion via ORM
    with session_scope(engine=db.engine) as session:
        version = ORMClsVersion(
            training_samples=result["training_samples"],
            positive_samples=result["positive_samples"],
            negative_samples=result["negative_samples"],
            cv_accuracy=result["cv_auc_mean"],
            cv_precision=None,
            cv_recall=None,
            active=True,
        )
        session.add(version)
        session.flush()
        version_id = version.id

        # Deactivate previous versions
        session.execute(
            update(ORMClsVersion)
            .where(ORMClsVersion.id != version_id)
            .values(active=False)
        )

        # Save model to disk using absolute path
        _MODELS_DIR.mkdir(parents=True, exist_ok=True)
        model_path = _MODELS_DIR / f"classifier_{user_id}_v{version_id}.pkl"
        with open(model_path, "wb") as f:
            pickle.dump(scorer.model, f)
        version.model_path = str(model_path)

    # Reset retrain counters
    db.save_user_setting(user_id, "labels_since_last_train", "0")
    db.save_user_setting(user_id, "retrain_pending", "false")

    log.info(
        "Classifier trained for user %d: %d samples, AUC=%.4f, model=%s",
        user_id,
        result["training_samples"],
        result["cv_auc_mean"],
        model_path,
    )

    return {
        "training_samples": result["training_samples"],
        "cv_auc_mean": result["cv_auc_mean"],
        "model_path": str(model_path),
    }
