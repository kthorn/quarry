"""Tests for the ranking pipeline core: config, context, registry, pipeline."""

import pytest

from quarry.rank.config import RankingConfig, StepConfig, get_default_config
from quarry.rank.context import PipelineContext, PipelineResult


class TestStepConfig:
    def test_defaults(self):
        sc = StepConfig(step_type="scorer", name="similarity")
        assert sc.enabled is True
        assert sc.params == {}

    def test_disabled(self):
        sc = StepConfig(step_type="scorer", name="foo", enabled=False)
        assert sc.enabled is False


class TestRankingConfig:
    def test_default(self):
        config = get_default_config()
        assert config.final_scorer_name == "similarity"
        assert len(config.steps) == 1
        assert config.steps[0].name == "similarity"

    def test_validate_final_scorer_missing(self):
        config = RankingConfig(
            steps=[
                StepConfig(step_type="scorer", name="a", enabled=True),
                StepConfig(step_type="scorer", name="b", enabled=True),
            ],
            final_scorer_name="c",
        )
        with pytest.raises(ValueError, match="final_scorer_name"):
            config.validate_final_scorer()

    def test_validate_final_scorer_disabled(self):
        config = RankingConfig(
            steps=[
                StepConfig(step_type="scorer", name="a", enabled=False),
            ],
            final_scorer_name="a",
        )
        with pytest.raises(ValueError, match="final_scorer_name"):
            config.validate_final_scorer()

    def test_validate_final_scorer_ok(self):
        config = RankingConfig(
            steps=[
                StepConfig(step_type="scorer", name="a", enabled=True),
            ],
            final_scorer_name="a",
        )
        config.validate_final_scorer()  # should not raise

    def test_serialization_roundtrip(self):
        config = RankingConfig(
            steps=[
                StepConfig(step_type="scorer", name="sim", params={"k": "v"}),
            ],
            final_scorer_name="sim",
        )
        json_str = config.model_dump_json()
        restored = RankingConfig.model_validate_json(json_str)
        assert restored.final_scorer_name == "sim"
        assert len(restored.steps) == 1
        assert restored.steps[0].params == {"k": "v"}


class TestPipelineContext:
    def test_defaults(self):
        ctx = PipelineContext()
        assert ctx.features == {}
        assert ctx.scores == {}
        assert ctx.final_score == 0.0
        assert ctx.dropped is False
        assert ctx.drop_reason is None

    def test_mutation(self):
        ctx = PipelineContext()
        ctx.features["f1"] = 0.5
        ctx.scores["s1"] = 0.8
        ctx.dropped = True
        ctx.drop_reason = "test"
        assert ctx.features["f1"] == 0.5
        assert ctx.scores["s1"] == 0.8
        assert ctx.dropped is True


class TestPipelineResult:
    def test_creation(self):
        ctx = PipelineContext(features={"a": 1.0}, scores={"b": 0.5})
        result = PipelineResult(context=ctx)
        assert result.context is ctx
        assert result.context.features["a"] == 1.0
        assert result.context.scores["b"] == 0.5
