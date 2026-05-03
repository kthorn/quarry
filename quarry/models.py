from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


@dataclass
class ParsedLocation:
    canonical_name: str
    city: str | None = None
    state: str | None = None
    state_code: str | None = None
    country: str | None = None
    country_code: str | None = None
    region: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    resolution_status: str = "resolved"
    raw_fragment: str | None = None


@dataclass
class ParseResult:
    work_model: str | None = None
    locations: list[ParsedLocation] = field(default_factory=list)


# ── Shared Catalog Models (no per-user data) ──────────────────


class Company(BaseModel):
    """Shared company catalog (no per-user data)."""

    id: int | None = None
    name: str
    domain: str | None = None
    careers_url: str | None = None
    ats_type: Literal["greenhouse", "lever", "ashby", "generic", "unknown"] = "unknown"
    ats_slug: str | None = None
    resolve_status: Literal["unresolved", "resolved", "failed"] = "unresolved"
    resolve_attempts: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RawPosting(BaseModel):
    company_id: int
    title: str
    url: str
    description: str | None = None
    location: str | None = None
    posted_at: datetime | None = None
    source_id: str | None = None
    source_type: str


class JobPosting(BaseModel):
    """Shared job posting catalog (no per-user data)."""

    id: int | None = None
    company_id: int
    title: str
    title_hash: str
    url: str
    description: str | None = None
    location: str | None = None
    work_model: str | None = None
    posted_at: datetime | None = None
    source_id: str | None = None
    source_type: str | None = None
    embedding: bytes | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


# ── Per-User Models ────────────────────────────────────────────


class User(BaseModel):
    id: int | None = None
    email: str
    name: str | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UserWatchlistItem(BaseModel):
    id: int | None = None
    user_id: int
    company_id: int
    active: bool = True
    crawl_priority: int = 5
    notes: str | None = None
    added_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UserPostingStatus(BaseModel):
    id: int | None = None
    user_id: int
    posting_id: int
    status: Literal["new", "seen", "applied", "rejected", "archived"] = "new"
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


class UserLabel(BaseModel):
    id: int | None = None
    user_id: int
    posting_id: int
    signal: Literal["positive", "negative", "applied", "skip"]
    notes: str | None = None
    labeled_at: datetime | None = None
    label_source: Literal["user", "inferred"] = "user"


class UserSearchQuery(BaseModel):
    id: int | None = None
    user_id: int
    query_text: str
    site: str | None = None
    active: bool = True
    added_reason: str | None = None
    retired_reason: str | None = None
    postings_found: int = 0
    positive_labels: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UserSimilarityScore(BaseModel):
    id: int | None = None
    user_id: int
    posting_id: int
    similarity_score: float
    computed_at: datetime | None = None


class UserClassifierScore(BaseModel):
    id: int | None = None
    user_id: int
    posting_id: int
    classifier_score: float
    model_version_id: int | None = None
    computed_at: datetime | None = None


class UserEnrichedPosting(BaseModel):
    id: int | None = None
    user_id: int
    posting_id: int
    fit_score: int | None = None
    role_tier: Literal["reach", "match", "strong_match"] | None = None
    fit_reason: str | None = None
    key_requirements: str | None = None
    enriched_at: datetime | None = None


class UserSetting(BaseModel):
    id: int | None = None
    user_id: int
    key: str
    value: str | None = None
    updated_at: datetime | None = None


# ── System-Level Models (unchanged) ───────────────────────────


class CrawlRun(BaseModel):
    id: int | None = None
    company_id: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: Literal["running", "success", "error", "partial"] | None = None
    postings_found: int = 0
    postings_new: int = 0
    error_message: str | None = None


class ClassifierVersion(BaseModel):
    id: int | None = None
    trained_at: datetime | None = None
    training_samples: int = 0
    positive_samples: int = 0
    negative_samples: int = 0
    cv_accuracy: float | None = None
    cv_precision: float | None = None
    cv_recall: float | None = None
    model_path: str | None = None
    active: bool = False
    notes: str | None = None


class AgentAction(BaseModel):
    id: int | None = None
    run_id: str | None = None
    tool_name: str
    tool_args: str | None = None
    tool_result: str | None = None
    rationale: str | None = None
    created_at: datetime | None = None


@dataclass
class FilterDecision:
    passed: bool
    skip_reason: str | None = None


class EnrichedPosting(BaseModel):
    posting_id: int
    user_id: int
    fit_score: int
    role_tier: Literal["reach", "match", "strong_match"]
    fit_reason: str
    key_requirements: list[str]


class DigestEntry(BaseModel):
    company_name: str
    title: str
    url: str
    role_tier: str | None = None
    fit_score: int | None = None
    similarity_score: float | None = None
    fit_reason: str | None = None
    location: str | None = None
    work_model: str | None = None
    location_names: list[str] = []
