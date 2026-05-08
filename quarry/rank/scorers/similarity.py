"""SimilarityScorer — reads pre-computed cosine similarity from user_similarity_scores."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from quarry.rank.base import Scorer
from quarry.rank.registry import register

if TYPE_CHECKING:
    from quarry.rank.context import PipelineContext

log = logging.getLogger(__name__)


@register("similarity")
class SimilarityScorer(Scorer):
    """Reads pre-computed similarity from the user_similarity_scores table.

    Requires `db.get_similarity_score(user_id, posting_id)` to be
    available on the Database instance injected into the context.
    """

    name: str = "similarity"

    def score(self, posting_id: int, context: "PipelineContext") -> float:
        db = getattr(context, "db", None)
        user_id = getattr(context, "user_id", 1)
        if db is None:
            log.warning("No db on context; returning 0.0")
            return 0.0
        score = db.get_similarity_score(user_id, posting_id)
        return score if score is not None else 0.0
