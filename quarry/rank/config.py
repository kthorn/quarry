"""Pydantic config models for the ranking pipeline.

RankingConfig is the inner JSON payload stored in pipeline_configs.config_json.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class StepConfig(BaseModel):
    """Configuration for a single step in the ranking pipeline."""

    step_type: Literal["ranking_filter", "feature", "scorer"]
    name: str  # registry key, e.g. "similarity"
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class RankingConfig(BaseModel):
    """The inner JSON payload stored in pipeline_configs.config_json.

    id is populated from PipelineConfig.id when loaded from the DB.
    """

    id: int | None = None  # PipelineConfig row ID
    steps: list[StepConfig] = Field(default_factory=list)
    final_scorer_name: str = "similarity"

    def validate_final_scorer(self) -> None:
        """Ensure final_scorer_name references an enabled scorer step."""
        scorer_names = {
            s.name for s in self.steps if s.step_type == "scorer" and s.enabled
        }
        if self.final_scorer_name not in scorer_names:
            raise ValueError(
                f"final_scorer_name '{self.final_scorer_name}' is not an enabled "
                f"scorer step (available: {sorted(scorer_names)})"
            )


def get_default_config() -> RankingConfig:
    """Return the default ranking config: similarity-only."""
    return RankingConfig(
        steps=[
            StepConfig(
                step_type="scorer",
                name="similarity",
                params={},
                enabled=True,
            )
        ],
        final_scorer_name="similarity",
    )
