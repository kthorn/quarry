"""RankingPipeline — orchestrates steps for each posting.

The primary entry point for running the ranking pipeline against postings.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from quarry.rank.base import FeatureExtractor, RankingFilter, Scorer
from quarry.rank.config import RankingConfig, get_default_config
from quarry.rank.context import PipelineContext, PipelineResult
from quarry.rank.registry import build_step

if TYPE_CHECKING:
    from quarry.store.db import Database

log = logging.getLogger(__name__)


class RankingPipeline:
    """Orchestrates ranking steps for job postings.

    Reorders steps by type: all RankingFilter first, then all
    FeatureExtractor, then all Scorer. If the user's config order
    differs, a warning is logged.
    """

    def __init__(
        self,
        steps: list,
        config: RankingConfig | None = None,
        db: "Database | None" = None,
        user_id: int = 1,
    ) -> None:
        self._steps = steps
        self.config = config or get_default_config()
        self.db = db
        self.user_id = user_id

    @classmethod
    def load_for_user(cls, db: "Database", user_id: int = 1) -> "RankingPipeline":
        """Load the active pipeline config for a user and build all steps."""
        config = db.get_active_pipeline_config(user_id)
        if config is None:
            log.info("No active pipeline config for user %d; using defaults", user_id)
            config = get_default_config()
        else:
            log.info(
                "Loading pipeline config id=%d for user %d with steps: %s",
                config.id,
                user_id,
                [(s.name, s.enabled) for s in config.steps],
            )
        steps = [build_step(step) for step in config.steps if step.enabled]
        log.info(
            "Built %d ranking steps: %s",
            len(steps),
            [type(s).__name__ for s in steps],
        )
        return cls(steps=steps, config=config, db=db, user_id=user_id)

    def _reorder_steps(self, steps: list) -> list:
        """Reorder steps: filters first, then feature extractors, then scorers."""
        filters = [s for s in steps if isinstance(s, RankingFilter)]
        extractors = [s for s in steps if isinstance(s, FeatureExtractor)]
        scorers = [s for s in steps if isinstance(s, Scorer)]

        reordered = filters + extractors + scorers
        if [type(s) for s in reordered] != [type(s) for s in steps]:
            orig_names = [getattr(s, "name", s.__class__.__name__) for s in steps]
            new_names = [getattr(s, "name", s.__class__.__name__) for s in reordered]
            log.warning(
                "Pipeline step order reordered: config had %s; executing as %s",
                orig_names,
                new_names,
            )
        return reordered

    def run(self, posting_id: int) -> PipelineResult:
        """Execute the pipeline on a single posting.

        Args:
            posting_id: ID of the posting to score.

        Returns:
            PipelineResult with the final context.
        """
        context = PipelineContext()
        context.db = self.db  # type: ignore[attr-defined]
        context.user_id = self.user_id  # type: ignore[attr-defined]

        ordered_steps = self._reorder_steps(self._steps)

        for step in ordered_steps:
            try:
                if isinstance(step, RankingFilter):
                    if not step.check(posting_id, context):
                        context.dropped = True
                        context.drop_reason = f"filter:{step.__class__.__name__}"
                        break
                elif isinstance(step, FeatureExtractor):
                    features = step.extract(posting_id, context)
                    context.features.update(features)
                elif isinstance(step, Scorer):
                    context.scores[step.name] = step.score(posting_id, context)
            except Exception:
                log.exception(
                    "Scorer '%s' raised exception; skipping",
                    getattr(step, "name", step),
                )

        context.final_score = context.scores.get(self.config.final_scorer_name, 0.0)
        return PipelineResult(context=context)
