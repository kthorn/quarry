"""Abstract base classes for ranking pipeline steps.

Three step types:
  - RankingFilter: hard reject postings (check returns bool)
  - FeatureExtractor: add computed features to context
  - Scorer: produce a 0-1 score

A single class may implement multiple interfaces (e.g., keyword heuristic
acting as both FeatureExtractor and Scorer).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quarry.rank.context import PipelineContext


class RankingFilter(ABC):
    """Hard reject postings. Runs first in the pipeline."""

    @abstractmethod
    def check(self, posting_id: int, context: "PipelineContext") -> bool:
        """Return False to drop this posting from the pipeline."""
        ...


class FeatureExtractor(ABC):
    """Add computed features to context. Runs after filters, before scorers."""

    @abstractmethod
    def extract(self, posting_id: int, context: "PipelineContext") -> dict[str, float]:
        """Return a dict of feature name → value to merge into context.features."""
        ...


class Scorer(ABC):
    """Produce a 0-1 score. Runs after feature extractors.

    Subclasses must set `name` as a class attribute (the registry key).
    """

    name: str = ""

    @abstractmethod
    def score(self, posting_id: int, context: "PipelineContext") -> float:
        """Compute a 0-1 score for the posting."""
        ...
