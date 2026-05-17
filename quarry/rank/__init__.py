"""Ranking pipeline — pluggable scorer framework for job posting ranking.

Public API:
    run_pipeline: Run the active ranking pipeline against postings.
    get_default_config: Return the default (similarity-only) ranking config.
"""

# Import scorers to populate the step registry via @register decorators.
# Without this, any code path that avoids __main__.py (e.g. the scheduler)
# never triggers registration and build_step() fails with all names unknown.
import quarry.rank.scorers as _scorers  # noqa: F401
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
