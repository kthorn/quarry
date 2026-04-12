"""Tests for location data models."""

from quarry.models import (
    FilterDecision,
    JobPosting,
    ParsedLocation,
    ParseResult,
    RawPosting,
)


def test_parsed_location_defaults():
    loc = ParsedLocation(
        canonical_name="San Francisco, CA",
        city="San Francisco",
        state="California",
        state_code="CA",
        country="United States",
        country_code="US",
        region="US-West",
    )
    assert loc.resolution_status == "resolved"
    assert loc.raw_fragment is None


def test_parsed_location_needs_review():
    loc = ParsedLocation(
        canonical_name="Unknown Place",
        city=None,
        state=None,
        state_code=None,
        country=None,
        country_code=None,
        region=None,
        resolution_status="needs_review",
        raw_fragment="Unknown Place",
    )
    assert loc.resolution_status == "needs_review"


def test_parse_result():
    loc = ParsedLocation(
        canonical_name="San Francisco, CA",
        city="San Francisco",
        state="California",
        state_code="CA",
        country="United States",
        country_code="US",
        region="US-West",
    )
    result = ParseResult(work_model="remote", locations=[loc])
    assert result.work_model == "remote"
    assert len(result.locations) == 1


def test_parse_result_no_locations():
    result = ParseResult(work_model="remote", locations=[])
    assert result.work_model == "remote"
    assert result.locations == []


def test_job_posting_has_work_model():
    p = JobPosting(
        company_id=1,
        title="Engineer",
        title_hash="abc",
        url="https://example.com",
        work_model="remote",
    )
    assert p.work_model == "remote"
    assert not hasattr(p, "remote")


def test_job_posting_work_model_null():
    p = JobPosting(
        company_id=1,
        title="Engineer",
        title_hash="abc",
        url="https://example.com",
    )
    assert p.work_model is None


def test_raw_posting_no_remote():
    r = RawPosting(
        company_id=1,
        title="Engineer",
        url="https://example.com",
        source_type="greenhouse",
    )
    assert not hasattr(r, "remote")


def test_filter_decision_passed():
    d = FilterDecision(passed=True)
    assert d.passed is True
    assert d.skip_reason is None


def test_filter_decision_rejected():
    d = FilterDecision(passed=False, skip_reason="blocklist")
    assert d.passed is False
    assert d.skip_reason == "blocklist"
