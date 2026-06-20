"""Similarity scoring and filter pipeline for job postings.

Scores postings against the ideal role embedding using cosine similarity,
then applies a filter pipeline (keyword blocklist, company, location) to
reject irrelevant postings before embedding.
"""

import logging
import re

import numpy as np
from pydantic import BaseModel, computed_field

from quarry.config import (
    CompanyFilterConfig,
    FiltersConfig,
    KeywordBlocklistConfig,
    LocationFilterConfig,
    NoneStrictness,
    TitleKeywordConfig,
)
from quarry.models import FilterDecision, JobPosting, ParseResult, RawPosting
from quarry.pipeline.embedder import embed_posting
from quarry.pipeline.locations import haversine_miles, parse_location

log = logging.getLogger(__name__)


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


class LocationMatchResult(BaseModel):
    """The outcome of evaluating a posting against a user's location+work-model prefs."""

    filter_active: bool  # is any location/work preference configured?
    work_type_match: bool  # does the posting's work_model fit user prefs?
    location_match: bool  # does a parsed location hit a target?
    location_relevant: (
        bool  # is location even considered? (False for remote / no targets)
    )

    @computed_field
    @property
    def passes(self) -> bool:
        """Overall: should this be shown by default?"""
        if not self.filter_active:
            return True
        return self.work_type_match and (
            self.location_match or not self.location_relevant
        )


def geographic_match(parse_result: ParseResult, config: LocationFilterConfig) -> bool:
    """True if any parsed location hits a target city / nearby_radius /
    accepted state / accepted region.

    Assumes parse_result.locations is non-empty and config has at least one
    target — callers gate on those.
    """
    for loc in parse_result.locations:
        if loc.city and loc.city.lower() in config._resolved_cities:
            return True
    if config.nearby_radius and config._resolved_target_coords:
        for loc in parse_result.locations:
            for target_lat, target_lon in config._resolved_target_coords:
                distance = haversine_miles(
                    loc.latitude, loc.longitude, target_lat, target_lon
                )
                if distance is not None and distance <= config.nearby_radius:
                    return True
    if config._resolved_states_from_accept:
        for loc in parse_result.locations:
            if (
                loc.state_code
                and loc.state_code.lower() in config._resolved_states_from_accept
            ):
                return True
    if config._resolved_regions_from_accept:
        for loc in parse_result.locations:
            if (
                loc.region
                and loc.region.lower() in config._resolved_regions_from_accept
            ):
                return True
    for loc in parse_result.locations:
        if not loc.city:
            if loc.state_code and loc.state_code.lower() in config._resolved_states:
                return True
            if (
                not loc.state_code
                and loc.region
                and loc.region.lower() in config._resolved_regions
            ):
                return True
    return False


def evaluate_location_match(
    location: str | None,
    work_model: str | None,
    config: LocationFilterConfig | None,
) -> LocationMatchResult:
    """Apply the location+work-model truth table for a user.

    Takes the raw posting `location` and `work_model` directly rather than a
    `JobPosting` instance. These two fields are the only inputs the truth
    table needs.

    This is the single source of truth for read-time filtering AND for the
    badges — the UI shows exactly what this function decided.
    """
    if config is None:
        return LocationMatchResult(
            filter_active=False,
            work_type_match=True,
            location_match=True,
            location_relevant=False,
        )

    targets_set = bool(
        config.target_location or config.accept_states or config.accept_regions
    )
    filter_active = targets_set or config.accept_remote

    # Step 1: Filter off
    if not filter_active:
        return LocationMatchResult(
            filter_active=False,
            work_type_match=True,
            location_match=True,
            location_relevant=False,
        )

    # Step 2: Work-type axis
    none_is_strict = config.none_strictness == NoneStrictness.STRICT
    if work_model == "remote":
        work_type_match = config.accept_remote
    elif work_model in ("onsite", "hybrid"):
        work_type_match = targets_set
    else:  # work_model is None
        if none_is_strict:
            work_type_match = targets_set
        else:
            work_type_match = True

    # Step 3: Location axis
    # - Remote postings ignore location
    # - Generous None also ignores location (assume acceptable)
    # - Strict None considers location (treat like in-person)
    if work_model == "remote":
        location_relevant = False
    elif work_model is None and not none_is_strict:
        location_relevant = False  # generous: pass regardless of location
    else:
        location_relevant = filter_active and targets_set

    if not location_relevant:
        return LocationMatchResult(
            filter_active=True,
            work_type_match=work_type_match,
            location_match=True,
            location_relevant=False,
        )

    # Location IS relevant — parse and check
    parse_result = parse_location(location)
    if not parse_result.locations:
        # No parseable locations — can't prove it's right or wrong
        # Generous: assume match (can't prove it's wrong)
        # Strict: assume no match
        location_match = not none_is_strict
        return LocationMatchResult(
            filter_active=True,
            work_type_match=work_type_match,
            location_match=location_match,
            location_relevant=True,
        )

    location_match = geographic_match(parse_result, config)
    return LocationMatchResult(
        filter_active=True,
        work_type_match=work_type_match,
        location_match=location_match,
        location_relevant=True,
    )


class TitleKeywordFilter:
    def get_config(self, filters_config: FiltersConfig | None) -> TitleKeywordConfig:
        if filters_config is None or filters_config.title_keyword is None:
            return TitleKeywordConfig()
        return filters_config.title_keyword

    def check(
        self,
        raw: RawPosting,
        posting: JobPosting,
        parse_result: ParseResult,
        company_name: str | None,
        config: TitleKeywordConfig,
    ) -> FilterDecision:
        if not config.keywords:
            return FilterDecision(passed=True)
        title_lower = (raw.title or "").lower()
        for keyword in config.keywords:
            if keyword.lower() in title_lower:
                return FilterDecision(passed=True)
        return FilterDecision(passed=False, skip_reason="title_keyword")


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
        if (
            not config.target_location
            and not config.accept_states
            and not config.accept_regions
        ):
            return FilterDecision(passed=True)
        if config.accept_remote and posting.work_model == "remote":
            log.debug(
                "Location filter: pass (remote work_model) for %s at %s",
                raw.title,
                company_name,
            )
            return FilterDecision(passed=True)
        if config.accept_remote and posting.work_model is None:
            log.debug(
                "Location filter: unknown work_model, falling through to geographic check for %s at %s (location=%s)",
                raw.title,
                company_name,
                raw.location,
            )
        if not parse_result.locations:
            return FilterDecision(passed=True)
        if geographic_match(parse_result, config):
            return FilterDecision(passed=True)
        return FilterDecision(passed=False, skip_reason="location")


FILTER_STEPS: list = [
    KeywordBlocklistFilter(),
    TitleKeywordFilter(),
    CompanyFilter(),
]
