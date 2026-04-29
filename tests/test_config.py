import os

os.environ["AWS_REGION"] = "us-west-2"  # Test env override

import pytest

from quarry.config import (
    CompanyFilterConfig,
    FiltersConfig,
    KeywordBlocklistConfig,
    LocationFilterConfig,
    Settings,
    load_config,
)


def test_load_config_from_yaml(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
db_path: test.db
similarity_threshold: 0.5
""")
    settings = load_config(config_file)
    assert settings.db_path == "test.db"
    assert settings.similarity_threshold == 0.5


def test_env_var_overrides_yaml(tmp_path):
    """Env vars should override YAML values"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
db_path: yaml-value.db
aws_region: yaml-region
""")
    # AWS_REGION is set in environment at top of file
    settings = load_config(config_file)
    # Env var should win
    assert settings.aws_region == "us-west-2"


def test_empty_filters_config_passes():
    config = FiltersConfig()
    assert config.keyword_blocklist is None
    assert config.company_filter is None
    assert config.location_filter is None


def test_keyword_blocklist_config_defaults():
    config = KeywordBlocklistConfig()
    assert config.keywords == []
    assert config.passlist == []


def test_company_filter_config_defaults():
    config = CompanyFilterConfig()
    assert config.allow == []
    assert config.deny == []


def test_location_filter_config_defaults():
    config = LocationFilterConfig()
    assert config.target_location == []
    assert config.accept_remote is True
    assert config.nearby_radius is None
    assert config.accept_states == []
    assert config.accept_regions == []


def test_filters_config_normalize_empty():
    config = FiltersConfig()
    config.normalize_config()
    assert config.location_filter is None


def test_location_filter_normalize_config_resolves_cities():
    config = LocationFilterConfig(
        target_location=["San Francisco"],
        accept_states=["CA"],
        accept_regions=["US-West"],
    )
    config.normalize_config()
    assert "san francisco" in config._resolved_cities
    assert "ca" in config._resolved_states
    assert "us-west" in config._resolved_regions


def test_location_filter_normalize_config_resolves_target_coords():
    config = LocationFilterConfig(target_location=["San Francisco"], nearby_radius=50)
    config.normalize_config()
    assert len(config._resolved_target_coords) >= 1
    lat, lon = config._resolved_target_coords[0]
    assert 37.7 < lat < 37.8
    assert -122.5 < lon < -122.3


def test_location_filter_nearby_radius_without_targets_raises():
    config = LocationFilterConfig(
        target_location=[], nearby_radius=50, accept_states=["CA"]
    )
    with pytest.raises(ValueError, match="nearby_radius"):
        config.normalize_config()


def test_settings_rejects_unknown_keys():
    """Verify extra='forbid' is set on Settings."""
    with pytest.raises(Exception):
        Settings(unknown_key="value")
