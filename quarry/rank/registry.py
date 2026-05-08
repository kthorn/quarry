"""Scorer registry — maps step names to scorer classes/instances.

Usage:
    @register("similarity")
    class SimilarityScorer(Scorer):
        ...
"""

from __future__ import annotations

import logging
from typing import Any

from quarry.rank.base import FeatureExtractor, RankingFilter, Scorer
from quarry.rank.config import StepConfig

log = logging.getLogger(__name__)

_registry: dict[str, type] = {}


def register(name: str):
    """Decorator to register a scorer/step class by name."""

    def decorator(cls: type) -> type:
        if name in _registry:
            log.warning("Re-registering scorer '%s' (was %s)", name, _registry[name])
        _registry[name] = cls
        return cls

    return decorator


def build_step(step_config: StepConfig) -> Any:
    """Instantiate a step from its StepConfig.

    Looks up the class in the registry and instantiates it with params.
    """
    cls = _registry.get(step_config.name)
    if cls is None:
        registered = sorted(_registry.keys())
        raise ValueError(
            f"Unknown step name '{step_config.name}'. "
            f"Registered: {registered or '(none)'}"
        )
    params = step_config.params
    return cls(**params) if params else cls()


def get_registered_names() -> list[str]:
    """Return sorted list of all registered step names."""
    return sorted(_registry.keys())


def get_step_info(name: str) -> dict[str, Any] | None:
    """Return metadata about a registered step."""
    cls = _registry.get(name)
    if cls is None:
        return None
    return {
        "name": name,
        "is_filter": issubclass(cls, RankingFilter),
        "is_feature_extractor": issubclass(cls, FeatureExtractor),
        "is_scorer": issubclass(cls, Scorer),
        "class_name": cls.__name__,
    }
