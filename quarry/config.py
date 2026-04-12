from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, PrivateAttr
from pydantic_settings import BaseSettings, SettingsConfigDict


class KeywordBlocklistConfig(BaseModel):
    keywords: list[str] = []
    passlist: list[str] = []


class CompanyFilterConfig(BaseModel):
    allow: list[str] = []
    deny: list[str] = []


class LocationFilterConfig(BaseModel):
    target_location: list[str] = []
    accept_remote: bool = True
    nearby_radius: int | None = None
    accept_states: list[str] = []
    accept_regions: list[str] = []

    _resolved_cities: set[str] = PrivateAttr(default_factory=set)
    _resolved_states: set[str] = PrivateAttr(default_factory=set)
    _resolved_regions: set[str] = PrivateAttr(default_factory=set)

    def normalize_config(self) -> None:
        from quarry.pipeline.locations import parse_location

        for entry in self.target_location:
            result = parse_location(entry)
            for loc in result.locations:
                if loc.city:
                    self._resolved_cities.add(loc.city.lower())
                if loc.state_code:
                    self._resolved_states.add(loc.state_code.lower())
        for state in self.accept_states:
            self._resolved_states.add(state.lower())
        self._resolved_regions = {r.lower() for r in self.accept_regions}


class FiltersConfig(BaseModel):
    keyword_blocklist: KeywordBlocklistConfig | None = None
    company_filter: CompanyFilterConfig | None = None
    location_filter: LocationFilterConfig | None = None

    def normalize_config(self) -> None:
        if self.location_filter and self.location_filter.target_location:
            self.location_filter.normalize_config()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    # Core
    db_path: str = "quarry.db"
    seed_file: str = "seed_data.yaml"

    # Role targeting
    ideal_role_description: str = ""
    similarity_threshold: float = 0.35
    dedup_window_days: int = 90

    # Crawling
    crawl_hour: int = 8
    crawl_schedule_cron: str = "0 7 * * *"
    careers_crawl_cron: str = "0 8 * * 1"
    reflection_after_crawl: bool = True

    # Notifications
    digest_time: str = "08:30"

    # LLM (via OpenRouter or Bedrock)
    llm_provider: Literal["bedrock", "openrouter"] = "bedrock"
    aws_region: str = "us-east-1"
    aws_profile: str | None = None
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-3-sonnet"
    max_reflection_tokens: int = 2048

    # Embeddings
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_provider: Literal["local", "openai"] = "local"
    openai_api_key: str = ""

    # User profile for enrichment
    user_profile: str = ""

    # Digest
    digest_top_n: int = 20

    # JobSpy crawler
    jobspy_sites: list[str] = [
        "indeed",
        "glassdoor",
        "google",
        "zip_recruiter",
        "linkedin",
    ]
    jobspy_results_wanted: int = 20
    jobspy_hours_old: int = 168

    # Crawler behavior
    max_retries: int = 3
    retry_base_delay: int = 2
    max_concurrent_per_host: int = 3
    request_timeout: int = 10
    max_response_bytes: int = 1048576  # 1MB
    max_redirects: int = 5

    # Filters
    filters: FiltersConfig | None = None


def load_config(config_path: Path | None = None) -> Settings:
    """Load config from YAML file, with env var overrides.

    Priority (highest to lowest): env vars > YAML > defaults
    """
    import os

    if config_path is None:
        candidates = [Path("config.yaml"), Path("quarry/config.yaml")]
        config_path = next((c for c in candidates if c.exists()), candidates[0])

    yaml_config = {}
    if config_path.exists():
        with open(config_path) as f:
            yaml_config = yaml.safe_load(f) or {}

    # Build override dict from env vars - these always win
    env_overrides = {}
    for field_name, field_info in Settings.model_fields.items():
        env_key = field_name.upper()
        if env_key in os.environ:
            env_val = os.environ[env_key]
            # Parse to correct type if needed
            anno = field_info.annotation
            if anno in (int, float, bool, str):
                env_overrides[field_name] = anno(env_val)
            elif getattr(anno, "__origin__", None) is list:
                env_overrides[field_name] = [x.strip() for x in env_val.split(",")]
            else:
                env_overrides[field_name] = env_val

    # Merge: YAML values, then env overrides (which take precedence)
    combined = {**yaml_config, **env_overrides}
    settings_obj = Settings(**combined)
    if settings_obj.filters:
        settings_obj.filters.normalize_config()
    return settings_obj


settings = load_config()
