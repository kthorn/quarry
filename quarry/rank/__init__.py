"""Ranking pipeline — pluggable scorer framework for job posting ranking.

Public API:
    run_pipeline: Run the active ranking pipeline against postings.
    get_default_config: Return the default (similarity-only) ranking config.
"""

from quarry.rank.config import RankingConfig, get_default_config
from quarry.rank.context import PipelineContext, PipelineResult
from quarry.rank.pipeline import RankingPipeline

__all__ = [
    "get_default_config",
    "PipelineContext",
    "PipelineResult",
    "RankingConfig",
    "RankingPipeline",
]
