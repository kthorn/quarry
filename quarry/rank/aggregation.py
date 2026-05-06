"""Built-in aggregator scorers.

WeightedAverageScorer combines multiple scorers into a weighted composite score.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from quarry.rank.base import Scorer
from quarry.rank.registry import register

if TYPE_CHECKING:
    from quarry.rank.context import PipelineContext

log = logging.getLogger(__name__)


@register("weighted_average")
class WeightedAverageScorer(Scorer):
    """Composite scorer that computes a weighted average of prior scorers.

    Params:
        weights: dict mapping scorer name → weight, e.g.
                 {"similarity": 0.6, "keyword_heuristic": 0.4}
    """

    name: str = "weighted_average"

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights: dict[str, float] = weights or {}

    def score(self, posting_id: int, context: "PipelineContext") -> float:
        total_weight = sum(self.weights.values())
        if total_weight == 0:
            return 0.0

        score = 0.0
        for name, weight in self.weights.items():
            if name in context.scores:
                score += weight * context.scores[name]
            else:
                log.warning("Scorer '%s' not in context.scores; treating as 0.0", name)
        return score / total_weight
