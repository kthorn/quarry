"""UserSettingsService — typed per-user settings with config.yaml fallback.

Provides a clean, typed interface over the raw user_settings key/value store.
Getters check the DB cache first; if no override exists, they fall back to
config.yaml. Complex filter configs are serialized via Pydantic's
model_dump_json() / model_validate(json.loads(...)).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, TypedDict


class JobSpyConfigDict(TypedDict):
    sites: list[str]
    results_wanted: int
    hours_old: int


if TYPE_CHECKING:
    from quarry.config import (
        KeywordBlocklistConfig,
        LocationFilterConfig,
        TitleKeywordConfig,
    )
    from quarry.store.db import Database


class UserSettingsService:
    """Typed access to per-user settings with config.yaml fallback.

    Usage:
        from quarry.store.db import get_db
        svc = UserSettingsService(get_db())
        print(svc.get_ideal_role_description())
    """

    def __init__(self, db: Database, user_id: int = 1):
        self.db = db
        self.user_id = user_id
        self._cache: dict[str, str | None] = db.get_user_settings_raw(user_id)

    # ── Simple scalar accessors ────────────────────────────────────

    def get_ideal_role_description(self) -> str:
        """Return ideal_role_description from DB, or config.yaml default."""
        val = self._cache.get("ideal_role_description")
        if val is not None:
            return val
        from quarry.config import settings

        return settings.ideal_role_description

    def set_ideal_role_description(self, text: str) -> None:
        """Save description text and recompute the ideal embedding.

        Uses set_ideal_embedding() which already saves both the embedding (hex)
        and the description text to user_settings.  Do NOT double-write the
        description text via save_user_setting().
        """
        from quarry.pipeline.embedder import set_ideal_embedding

        set_ideal_embedding(self.db, text, self.user_id)
        self._cache["ideal_role_description"] = text
        # Force re-read next time — the embedding changed.
        self._cache["ideal_role_embedding"] = None

    def get_similarity_threshold(self) -> float:
        """Return similarity_threshold from DB, or config.yaml default."""
        val = self._cache.get("similarity_threshold")
        if val is not None:
            return float(val)
        from quarry.config import settings

        return settings.similarity_threshold

    def set_similarity_threshold(self, value: float) -> None:
        """Persist similarity_threshold to DB and update cache."""
        val_str = str(value)
        self.db.save_user_setting(self.user_id, "similarity_threshold", val_str)
        self._cache["similarity_threshold"] = val_str

    # ── Complex config accessors (return None when no DB override) ──

    def get_keyword_blocklist(self) -> KeywordBlocklistConfig | None:
        """Return KeywordBlocklistConfig from DB, or None (use config.yaml).

        Returns:
            Parsed KeywordBlocklistConfig when a DB entry exists (even if empty).
            None when no DB entry exists — caller falls back to config.yaml.
        """
        val = self._cache.get("keyword_blocklist")
        if val is None:
            return None
        from quarry.config import KeywordBlocklistConfig

        return KeywordBlocklistConfig.model_validate(json.loads(val))

    def set_keyword_blocklist(self, config: KeywordBlocklistConfig) -> None:
        """Serialize to JSON {keywords:[], passlist:[]}, save to user_settings."""
        json_str = config.model_dump_json()
        self.db.save_user_setting(self.user_id, "keyword_blocklist", json_str)
        self._cache["keyword_blocklist"] = json_str

    def get_title_keywords(self) -> TitleKeywordConfig | None:
        """Return TitleKeywordConfig from DB, or None (use config.yaml)."""
        val = self._cache.get("title_keywords")
        if val is None:
            return None
        from quarry.config import TitleKeywordConfig

        return TitleKeywordConfig.model_validate(json.loads(val))

    def set_title_keywords(self, config: TitleKeywordConfig) -> None:
        """Serialize to JSON {keywords:[]}."""
        json_str = config.model_dump_json()
        self.db.save_user_setting(self.user_id, "title_keywords", json_str)
        self._cache["title_keywords"] = json_str

    def get_location_filter(self) -> LocationFilterConfig | None:
        """Deserialize from JSON, then call .normalize_config() to resolve
        city/state names to lat/lon (populates PrivateAttr fields)."""
        val = self._cache.get("location_filter")
        if val is None:
            return None
        from quarry.config import LocationFilterConfig

        cfg = LocationFilterConfig.model_validate(json.loads(val))
        cfg.normalize_config()
        return cfg

    def set_location_filter(self, config: LocationFilterConfig) -> None:
        """Serialize to full dict (PrivateAttr fields are NOT serialized)."""
        json_str = config.model_dump_json()
        self.db.save_user_setting(self.user_id, "location_filter", json_str)
        self._cache["location_filter"] = json_str

    def get_jobspy_config(self) -> JobSpyConfigDict:
        """Return dict with keys: sites, results_wanted, hours_old.

        Returns config.yaml defaults if no DB override.
        """
        val = self._cache.get("jobspy_config")
        if val is not None:
            return json.loads(val)
        from quarry.config import settings

        return {
            "sites": settings.jobspy_sites,
            "results_wanted": settings.jobspy_results_wanted,
            "hours_old": settings.jobspy_hours_old,
        }

    def set_jobspy_config(
        self, sites: list[str], results_wanted: int, hours_old: int
    ) -> None:
        """Serialize to JSON {sites:[...], results_wanted:N, hours_old:N}."""
        payload = {
            "sites": sites,
            "results_wanted": results_wanted,
            "hours_old": hours_old,
        }
        json_str = json.dumps(payload)
        self.db.save_user_setting(self.user_id, "jobspy_config", json_str)
        self._cache["jobspy_config"] = json_str
