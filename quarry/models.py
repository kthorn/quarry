from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Company(BaseModel):
    id: int | None = None
    name: str
    domain: str | None = None
    careers_url: str | None = None
    ats_type: Literal["greenhouse", "lever", "ashby", "generic", "unknown"] = "unknown"
    ats_slug: str | None = None
    active: bool = True
    crawl_priority: int = 5
    notes: str | None = None
    added_by: str = "seed"
    added_reason: str | None = None
    last_crawled_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RawPosting(BaseModel):
    company_id: int
    title: str
    url: str
    description: str | None = None
    location: str | None = None
    remote: bool | None = None
    posted_at: datetime | None = None
    source_id: str | None = None
    source_type: str


class JobPosting(BaseModel):
    id: int | None = None
    company_id: int
    title: str
    title_hash: str
    url: str
    description: str | None = None
    location: str | None = None
    remote: bool | None = None
    posted_at: datetime | None = None
    source_id: str | None = None
    source_type: str | None = None

    similarity_score: float | None = None
    classifier_score: float | None = None
    embedding: bytes | None = None

    fit_score: int | None = None
    role_tier: Literal["reach", "match", "strong_match"] | None = None
    fit_reason: str | None = None
    key_requirements: str | None = None
    enriched_at: datetime | None = None

    status: Literal["new", "seen", "applied", "rejected", "archived"] = "new"
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


class Label(BaseModel):
    id: int | None = None
    posting_id: int
    signal: Literal["positive", "negative", "applied", "skip"]
    notes: str | None = None
    labeled_at: datetime | None = None
    label_source: Literal["user", "inferred"] = "user"


class CrawlRun(BaseModel):
    id: int | None = None
    company_id: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: Literal["success", "error", "partial"] | None = None
    postings_found: int = 0
    postings_new: int = 0
    error_message: str | None = None


class SearchQuery(BaseModel):
    id: int | None = None
    query_text: str
    site: str | None = None
    active: bool = True
    added_by: str = "user"
    added_reason: str | None = None
    retired_reason: str | None = None
    postings_found: int = 0
    positive_labels: int = 0
    created_at: datetime | None = None


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


class FilterResult(BaseModel):
    posting: RawPosting
    passed: bool
    skip_reason: Literal["duplicate", "blocklist", "low_similarity"] | None = None
    similarity_score: float | None = None


class EnrichedPosting(BaseModel):
    posting_id: int
    fit_score: int
    role_tier: Literal["reach", "match", "strong_match"]
    fit_reason: str
    key_requirements: list[str]


class DigestEntry(BaseModel):
    company_name: str
    title: str
    url: str
    role_tier: str
    fit_score: int
    similarity_score: float
    fit_reason: str
    location: str | None = None
