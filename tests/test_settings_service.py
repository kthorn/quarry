"""Tests for UserSettingsService — typed per-user settings with config.yaml fallback."""

import json
from unittest.mock import patch

import pytest

from quarry.config import (
    KeywordBlocklistConfig,
    LocationFilterConfig,
    TitleKeywordConfig,
)
from quarry.settings_service import UserSettingsService
from quarry.store.db import init_db

# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    """Create a fresh in-memory-backed database with schema."""
    return init_db(tmp_path / "test.db")


@pytest.fixture
def svc(db):
    """Create a UserSettingsService backed by the test database."""
    return UserSettingsService(db)


# ── Ideal Role Description ────────────────────────────────────────


class TestIdealRoleDescription:
    def test_get_falls_back_to_config_when_no_db_entry(self, svc):
        """When no DB entry exists, the config.yaml default is returned."""
        result = svc.get_ideal_role_description()
        from quarry.config import settings

        assert result == settings.ideal_role_description

    def test_set_then_get(self, svc, db):
        """After setting, get returns the saved value."""
        with patch(
            "quarry.pipeline.embedder.set_ideal_embedding", return_value=None
        ) as mock_set:
            svc.set_ideal_role_description("Senior Python Developer")
            mock_set.assert_called_once_with(
                svc.db, "Senior Python Developer", svc.user_id
            )
        assert svc.get_ideal_role_description() == "Senior Python Developer"

    def test_set_updates_cache(self, svc, db):
        """Cache is updated after set — no second DB read needed."""
        with patch("quarry.pipeline.embedder.set_ideal_embedding"):
            svc.set_ideal_role_description("ML Engineer")
        # Should hit cache, not re-query DB
        assert svc.get_ideal_role_description() == "ML Engineer"

    def test_set_clears_embedding_cache(self, svc):
        """Setting the description invalidates the embedding cache."""
        with patch("quarry.pipeline.embedder.set_ideal_embedding"):
            svc.set_ideal_role_description("DevOps Engineer")
        assert svc._cache.get("ideal_role_embedding") is None


# ── Similarity Threshold ──────────────────────────────────────────


class TestSimilarityThreshold:
    def test_get_falls_back_to_config_when_no_db_entry(self, svc):
        """When no DB entry exists, the config.yaml default is returned."""
        result = svc.get_similarity_threshold()
        from quarry.config import settings

        assert result == settings.similarity_threshold

    def test_set_then_get(self, svc, db):
        """After setting, get returns the saved value as float."""
        svc.set_similarity_threshold(0.42)
        result = svc.get_similarity_threshold()
        assert result == 0.42
        assert isinstance(result, float)

    def test_set_then_get_boundary_values(self, svc, db):
        """Test edge cases: 0.0 and 1.0."""
        svc.set_similarity_threshold(0.0)
        assert svc.get_similarity_threshold() == 0.0

        svc.set_similarity_threshold(1.0)
        assert svc.get_similarity_threshold() == 1.0


# ── Keyword Blocklist ─────────────────────────────────────────────


class TestKeywordBlocklist:
    def test_get_returns_none_when_no_db_entry(self, svc):
        """No DB override → returns None (caller falls back to config.yaml)."""
        assert svc.get_keyword_blocklist() is None

    def test_set_then_get_with_keywords(self, svc):
        """Serialization round-trip with populated keywords/passlist."""
        config = KeywordBlocklistConfig(
            keywords=["react", "node"], passlist=["node.js"]
        )
        svc.set_keyword_blocklist(config)

        result = svc.get_keyword_blocklist()
        assert result is not None
        assert result.keywords == ["react", "node"]
        assert result.passlist == ["node.js"]

    def test_set_then_get_empty_config(self, svc):
        """An empty KeywordBlocklistConfig is stored and retrieved (not None)."""
        svc.set_keyword_blocklist(KeywordBlocklistConfig())
        result = svc.get_keyword_blocklist()
        assert result is not None
        assert result.keywords == []
        assert result.passlist == []

    def test_empty_config_distinct_from_no_override(self, svc):
        """User explicitly clearing the blocklist (empty config) is distinct
        from having no DB override at all (None)."""
        # Before: no override → None
        assert svc.get_keyword_blocklist() is None

        # After saving empty config: returns parsed config (not None)
        svc.set_keyword_blocklist(KeywordBlocklistConfig())
        result = svc.get_keyword_blocklist()
        assert result is not None
        assert result.keywords == []


# ── Title Keywords ────────────────────────────────────────────────


class TestTitleKeywords:
    def test_get_returns_none_when_no_db_entry(self, svc):
        assert svc.get_title_keywords() is None

    def test_set_then_get(self, svc):
        config = TitleKeywordConfig(keywords=["engineer", "developer"])
        svc.set_title_keywords(config)

        result = svc.get_title_keywords()
        assert result is not None
        assert result.keywords == ["engineer", "developer"]

    def test_empty_config(self, svc):
        svc.set_title_keywords(TitleKeywordConfig())
        result = svc.get_title_keywords()
        assert result is not None
        assert result.keywords == []


# ── Location Filter ───────────────────────────────────────────────


class TestLocationFilter:
    def test_get_returns_none_when_no_db_entry(self, svc):
        assert svc.get_location_filter() is None

    def test_set_then_get_basic_fields(self, svc):
        """Basic fields survive the JSON round-trip."""
        config = LocationFilterConfig(
            target_location=["San Francisco, CA"],
            accept_remote=True,
            nearby_radius=50,
            accept_states=["CA", "OR"],
            accept_regions=["US-West"],
        )
        svc.set_location_filter(config)

        result = svc.get_location_filter()
        assert result is not None
        assert result.target_location == ["San Francisco, CA"]
        assert result.accept_remote is True
        assert result.nearby_radius == 50
        assert result.accept_states == ["CA", "OR"]
        assert result.accept_regions == ["US-West"]

    def test_private_attrs_not_serialized(self, svc):
        """PrivateAttr fields (_resolved_*) are NOT in the DB JSON."""
        config = LocationFilterConfig(accept_states=["CA"])
        svc.set_location_filter(config)

        # Read the raw JSON from DB to verify PrivateAttr exclusion
        raw = svc.db.get_user_setting(svc.user_id, "location_filter")
        assert raw is not None
        data = json.loads(raw)
        assert "_resolved_cities" not in data
        assert "_resolved_target_coords" not in data

    def test_normalize_config_called_on_get(self, svc):
        """get_location_filter calls normalize_config(), populating
        PrivateAttr resolved fields."""
        config = LocationFilterConfig(
            target_location=["San Francisco, CA"],
            accept_states=["NY"],
        )
        svc.set_location_filter(config)

        result = svc.get_location_filter()
        assert result is not None
        # After normalize_config, resolved fields should be populated
        assert "san francisco" in result._resolved_cities
        assert "ca" in result._resolved_states
        # San Francisco should resolve to coordinates
        assert len(result._resolved_target_coords) > 0

    def test_empty_config(self, svc):
        svc.set_location_filter(LocationFilterConfig())
        result = svc.get_location_filter()
        assert result is not None
        assert result.target_location == []
        assert result.accept_remote is False


# ── JobSpy Config ─────────────────────────────────────────────────


class TestJobSpyConfig:
    def test_get_falls_back_to_config_when_no_db_entry(self, svc):
        result = svc.get_jobspy_config()
        from quarry.config import settings

        assert result["sites"] == settings.jobspy_sites
        assert result["results_wanted"] == settings.jobspy_results_wanted
        assert result["hours_old"] == settings.jobspy_hours_old

    def test_set_then_get(self, svc):
        svc.set_jobspy_config(
            sites=["indeed", "linkedin"], results_wanted=10, hours_old=72
        )
        result = svc.get_jobspy_config()
        assert result["sites"] == ["indeed", "linkedin"]
        assert result["results_wanted"] == 10
        assert result["hours_old"] == 72

    def test_set_partial_sites(self, svc):
        svc.set_jobspy_config(sites=["google"], results_wanted=5, hours_old=24)
        result = svc.get_jobspy_config()
        assert result["sites"] == ["google"]


# ── Cache behavior ────────────────────────────────────────────────


class TestCacheBehavior:
    def test_cache_loaded_on_init(self, db):
        """The cache is populated from DB during __init__."""
        db.save_user_setting(1, "similarity_threshold", "0.55")
        svc = UserSettingsService(db)
        assert "similarity_threshold" in svc._cache
        assert svc._cache["similarity_threshold"] == "0.55"

    def test_cache_reflects_new_setting(self, svc):
        """After set, the cache is updated without re-reading from DB."""
        svc.set_similarity_threshold(0.99)
        assert svc._cache["similarity_threshold"] == "0.99"

    def test_multi_key_cache_independence(self, svc):
        """Setting one key does not affect other cache entries."""
        svc.set_similarity_threshold(0.33)
        svc.set_keyword_blocklist(KeywordBlocklistConfig(keywords=["java"]))

        # similarity_threshold should still be in cache
        assert svc._cache["similarity_threshold"] == "0.33"
        # keyword_blocklist should be in cache as JSON string
        assert svc._cache["keyword_blocklist"] is not None
        data = json.loads(svc._cache["keyword_blocklist"])
        assert data["keywords"] == ["java"]


# ── Multi-user isolation ──────────────────────────────────────────


class TestMultiUser:
    def test_different_users_have_independent_settings(self, db):
        """Settings for user 1 do not leak into user 2."""
        # Seed user 2 (init_db only seeds user 1)
        import sqlite3

        conn = sqlite3.connect(str(db.engine.url).replace("sqlite:///", ""))
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email) VALUES (2, 'user2@test.com')"
        )
        conn.commit()
        conn.close()

        svc1 = UserSettingsService(db, user_id=1)
        svc2 = UserSettingsService(db, user_id=2)

        svc1.set_similarity_threshold(0.25)
        svc2.set_similarity_threshold(0.75)

        assert svc1.get_similarity_threshold() == 0.25
        assert svc2.get_similarity_threshold() == 0.75

    def test_user_without_settings_falls_back_to_config(self, db):
        """A fresh user with no DB overrides falls back to config.yaml."""
        # User 99 has never saved any settings
        from quarry.config import settings

        svc = UserSettingsService(db, user_id=99)

        assert svc.get_ideal_role_description() == settings.ideal_role_description
        assert svc.get_similarity_threshold() == settings.similarity_threshold
        assert svc.get_keyword_blocklist() is None
        assert svc.get_title_keywords() is None
        assert svc.get_location_filter() is None


# ── JSON round-trip fidelity ──────────────────────────────────────


class TestJSONRoundTrip:
    """Verify that each config type survives serialize→deserialize identically."""

    def test_keyword_blocklist_roundtrip(self, svc):
        original = KeywordBlocklistConfig(
            keywords=["python", "django"], passlist=["pythonista"]
        )
        svc.set_keyword_blocklist(original)
        result = svc.get_keyword_blocklist()
        assert result is not None
        assert result.model_dump() == original.model_dump()

    def test_title_keywords_roundtrip(self, svc):
        original = TitleKeywordConfig(keywords=["backend", "api"])
        svc.set_title_keywords(original)
        result = svc.get_title_keywords()
        assert result is not None
        assert result.model_dump() == original.model_dump()

    def test_location_filter_public_fields_roundtrip(self, svc):
        """Public fields survive round-trip; PrivateAttr fields are not
        serialized and are recomputed by normalize_config()."""
        original = LocationFilterConfig(
            target_location=["San Francisco, CA"],
            accept_remote=False,
            nearby_radius=25,
            accept_states=["TX"],
        )
        svc.set_location_filter(original)
        result = svc.get_location_filter()
        assert result is not None

        # Public fields should match
        assert result.target_location == original.target_location
        assert result.accept_remote == original.accept_remote
        assert result.nearby_radius == original.nearby_radius
        assert result.accept_states == original.accept_states
