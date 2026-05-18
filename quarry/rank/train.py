"""Classifier training logic shared between CLI and web UI."""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import update

from quarry.pipeline.embedder import deserialize_embedding, get_embedding_dim
from quarry.rank.config import RankingConfig, StepConfig
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
    interest_labels = []
    embeddings = []

    for row in rows:
        interest_bool, emb_bytes, posting_id = row
        if emb_bytes is None:
            continue
        try:
            emb = deserialize_embedding(emb_bytes, dim)
        except (ValueError, TypeError):
            continue
        posting = SimpleNamespace(embedding=emb, id=posting_id)
        embeddings.append(posting)
        interest_labels.append(interest_bool)

    if len(interest_labels) < min_labels:
        return {
            "error": (
                f"Not enough labeled postings ({len(interest_labels)} < {min_labels}). "
                "Label more postings first."
            ),
            "training_samples": len(interest_labels),
        }

    scorer = ClassifierScorer(min_training_labels=min_labels)
    result = scorer.fit(interest_labels, embeddings)
    if result is None:
        return {
            "error": (
                "Training failed — check logs for details. "
                f"Had {len(interest_labels)} labeled postings, "
                f"but the classifier requires at least {min_labels} with both "
                "positive and negative classes present and enough per class for "
                "cross-validation."
            ),
            "training_samples": len(interest_labels),
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
        # user_id is caller-controlled; sanitize to prevent path traversal
        safe_id = str(user_id).replace(".", "").replace("/", "")
        model_path = _MODELS_DIR / f"classifier_{safe_id}_v{version_id}.pkl"
        with open(model_path, "wb") as f:
            pickle.dump(scorer.model, f)
        version.model_path = str(model_path)

    # Reset retrain counters
    db.save_user_setting(user_id, "labels_since_last_train", "0")
    db.save_user_setting(user_id, "retrain_pending", "false")

    # ── Re-score all postings with the new classifier ─────────
    _rescore_all_postings(db, user_id, scorer, version_id)

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


def _rescore_all_postings(
    db: Any,
    user_id: int,
    scorer: ClassifierScorer,
    version_id: int,
) -> int:
    """Score every posting with the trained classifier and update rankings.

    Returns the number of postings scored.
    """

    dim = get_embedding_dim()
    postings = db.get_all_postings_with_embeddings()
    if not postings:
        return 0

    # Create a pipeline config that uses the classifier as the final scorer
    new_config = RankingConfig(
        steps=[
            StepConfig(step_type="scorer", name="similarity", params={}, enabled=True),
            StepConfig(step_type="scorer", name="classifier", params={}, enabled=True),
        ],
        final_scorer_name="classifier",
    )
    pipeline_config_id = db.insert_pipeline_config(
        user_id,
        new_config,
        description=f"classifier v{version_id}",
    )

    scored = 0
    for posting in postings:
        if posting.embedding is None:
            continue
        try:
            emb = deserialize_embedding(posting.embedding, dim)
        except (ValueError, TypeError):
            continue
        cls_score = float(scorer.model.predict_proba(emb.reshape(1, -1))[0][1])
        sim_score = db.get_similarity_score(user_id, posting.id) or 0.0
        db.upsert_classifier_score(user_id, posting.id, cls_score, version_id)
        db.upsert_ranking_score(
            user_id=user_id,
            posting_id=posting.id,
            pipeline_config_id=pipeline_config_id,
            composite_score=cls_score,
            component_scores={"classifier": cls_score, "similarity": sim_score},
        )
        scored += 1

    log.info(
        "Re-scored %d postings with classifier v%d (pipeline config %d)",
        scored,
        version_id,
        pipeline_config_id,
    )
    return scored
