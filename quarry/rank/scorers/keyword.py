"""KeywordHeuristicScorer — configurable keyword rules with weights.

Implements both FeatureExtractor and Scorer. Rules are configured
via the `rules` param: list of dicts with pattern, field, weight.
The score is a sigmoid-normalized sum of weighted matches.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from quarry.rank.base import FeatureExtractor, Scorer
from quarry.rank.registry import register

if TYPE_CHECKING:
    from quarry.rank.context import PipelineContext

log = logging.getLogger(__name__)


class KeywordRule(BaseModel):
    """A single keyword rule: match pattern in field, assign weight."""

    pattern: str
    field: str  # "title" or "description"
    weight: float = 1.0


def _normalize_to_01(x: float) -> float:
    """Sigmoid to map unbounded scores into [0, 1]."""
    return 1.0 / (1.0 + math.exp(-x))


@register("keyword_heuristic")
class KeywordHeuristicScorer(FeatureExtractor, Scorer):
    """Scorer that matches keyword patterns against posting fields.

    The `rules` param is a list of KeywordRule dicts. During extract(),
    it sets context.features[f"kw_{rule.pattern}"] = 1.0 or 0.0.
    During score(), it computes a weighted sum and normalizes via sigmoid.
    """

    name: str = "keyword_heuristic"

    def __init__(self, rules: list[dict[str, Any]] | None = None) -> None:
        self._rules: list[KeywordRule] = []
        if rules:
            for r in rules:
                self._rules.append(KeywordRule(**r))

    @property
    def rules(self) -> list[KeywordRule]:
        return self._rules

    def _get_field_text(
        self, posting_id: int, field: str, context: "PipelineContext"
    ) -> str:
        """Look up posting field text from the DB on context."""
        db = getattr(context, "db", None)
        if db is None:
            return ""
        posting = db.get_posting_by_id(posting_id)
        if posting is None:
            return ""
        if field == "title":
            return posting.title or ""
        if field == "description":
            return posting.description or ""
        return ""

    def extract(self, posting_id: int, context: "PipelineContext") -> dict[str, float]:
        features: dict[str, float] = {}
        for rule in self._rules:
            text = self._get_field_text(posting_id, rule.field, context).lower()
            match = rule.pattern.lower() in text
            features[f"kw_{rule.pattern}"] = 1.0 if match else 0.0
        return features

    def score(self, posting_id: int, context: "PipelineContext") -> float:
        raw = 0.0
        for rule in self._rules:
            feat_key = f"kw_{rule.pattern}"
            raw += rule.weight * context.features.get(feat_key, 0.0)
        return _normalize_to_01(raw)
