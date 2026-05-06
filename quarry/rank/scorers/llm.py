"""LLMEnrichmentScorer — LLM fit assessment with caching.

Calls LLM to assess posting fit against user profile. Results cached
in user_enriched_postings table.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from quarry.rank.base import Scorer
from quarry.rank.registry import register

if TYPE_CHECKING:
    from quarry.rank.context import PipelineContext

log = logging.getLogger(__name__)


@register("llm_enrichment")
class LLMEnrichmentScorer(Scorer):
    """LLM-based fit assessment scorer.

    Reads cached enrichment from user_enriched_postings. If not cached,
    returns 0.0 (actual LLM calls are deferred to a batch enrichment step
    outside the scoring pipeline).
    """

    name: str = "llm_enrichment"

    def score(self, posting_id: int, context: "PipelineContext") -> float:
        db = getattr(context, "db", None)
        user_id = getattr(context, "user_id", 1)
        if db is None:
            return 0.0

        enriched = db.get_enriched_posting(user_id, posting_id)
        if enriched and enriched.fit_score is not None:
            score = enriched.fit_score / 10.0
            return max(0.0, min(1.0, score))

        return 0.0
