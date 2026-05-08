"""Pipeline context and result types."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PipelineContext(BaseModel):
    """Mutable context carried through the ranking pipeline for a single posting.

    Accumulates features and scores as steps execute, and tracks whether
    the posting was dropped by a RankingFilter.
    """

    model_config = ConfigDict(extra="allow")

    features: dict[str, float] = {}
    scores: dict[str, float] = {}
    final_score: float = 0.0
    dropped: bool = False
    drop_reason: str | None = None

    # Injected by the pipeline before execution (not Pydantic fields):
    # db: Database — database handle for scorers that need it
    # user_id: int — current user for per-user lookups


class PipelineResult:
    """Result of running a posting through the ranking pipeline.

    Carries the context (scores, features, dropped state) so callers
    can extract composite and component scores for persistence.
    """

    __slots__ = ("context",)

    def __init__(self, context: PipelineContext) -> None:
        self.context = context
