"""Similarity scoring and filter pipeline for job postings.

Scores postings against the ideal role embedding using cosine similarity,
then applies a filter pipeline (keyword blocklist, company, location) to
reject irrelevant postings before embedding.
"""

import re

import numpy as np

from quarry.config import (
    CompanyFilterConfig,
    FiltersConfig,
    KeywordBlocklistConfig,
    LocationFilterConfig,
)
from quarry.models import FilterDecision, JobPosting, ParseResult, RawPosting
from quarry.pipeline.embedder import embed_posting


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def score_similarity(
    posting_embedding: np.ndarray, ideal_embedding: np.ndarray
) -> float:
    """Score a posting's relevance against the ideal role embedding."""
    return cosine_similarity(posting_embedding, ideal_embedding)


def embed_and_score(
    raw: RawPosting, ideal_embedding: np.ndarray
) -> tuple[float, np.ndarray]:
    """Embed a posting and compute similarity score. Returns (score, embedding)."""
    embedding = embed_posting(raw)
    score = score_similarity(embedding, ideal_embedding)
    return round(score, 4), embedding


def _normalize_company_name(name: str) -> str:
    return re.sub(r"[^\w\s]", "", name.lower()).strip()


class KeywordBlocklistFilter:
    def get_config(
        self, filters_config: FiltersConfig | None
    ) -> KeywordBlocklistConfig:
        if filters_config is None or filters_config.keyword_blocklist is None:
            return KeywordBlocklistConfig()
        return filters_config.keyword_blocklist

    def check(
        self,
        raw: RawPosting,
        posting: JobPosting,
        parse_result: ParseResult,
        company_name: str | None,
        config: KeywordBlocklistConfig,
    ) -> FilterDecision:
        if not config.keywords:
            return FilterDecision(passed=True)
        text = " ".join(
            filter(None, [raw.title, raw.description, raw.location])
        ).lower()
        for phrase in config.keywords:
            if phrase.lower() in text:
                for override in config.passlist:
                    if override.lower() in text:
                        return FilterDecision(passed=True)
                return FilterDecision(passed=False, skip_reason="blocklist")
        return FilterDecision(passed=True)


class CompanyFilter:
    def get_config(self, filters_config: FiltersConfig | None) -> CompanyFilterConfig:
        if filters_config is None or filters_config.company_filter is None:
            return CompanyFilterConfig()
        return filters_config.company_filter

    def check(
        self,
        raw: RawPosting,
        posting: JobPosting,
        parse_result: ParseResult,
        company_name: str | None,
        config: CompanyFilterConfig,
    ) -> FilterDecision:
        if not company_name:
            return FilterDecision(passed=True)
        normalized = _normalize_company_name(company_name)
        if config.allow:
            if any(
                _normalize_company_name(a) in normalized
                or normalized in _normalize_company_name(a)
                for a in config.allow
            ):
                return FilterDecision(passed=True)
            return FilterDecision(passed=False, skip_reason="company_allow_skip")
        if config.deny:
            if any(_normalize_company_name(d) in normalized for d in config.deny):
                return FilterDecision(passed=False, skip_reason="company_deny")
        return FilterDecision(passed=True)


class LocationFilter:
    def get_config(self, filters_config: FiltersConfig | None) -> LocationFilterConfig:
        if filters_config is None or filters_config.location_filter is None:
            return LocationFilterConfig()
        return filters_config.location_filter

    def check(
        self,
        raw: RawPosting,
        posting: JobPosting,
        parse_result: ParseResult,
        company_name: str | None,
        config: LocationFilterConfig,
    ) -> FilterDecision:
        if not config.target_location:
            return FilterDecision(passed=True)
        if config.accept_remote and parse_result.work_model == "remote":
            return FilterDecision(passed=True)
        if not parse_result.locations:
            return FilterDecision(passed=True)
        for loc in parse_result.locations:
            if loc.city and loc.city.lower() in config._resolved_cities:
                return FilterDecision(passed=True)
            if loc.state_code and loc.state_code.lower() in config._resolved_states:
                return FilterDecision(passed=True)
            if loc.region and loc.region.lower() in config._resolved_regions:
                return FilterDecision(passed=True)
        return FilterDecision(passed=False, skip_reason="location")


FILTER_STEPS: list = [KeywordBlocklistFilter(), CompanyFilter(), LocationFilter()]
