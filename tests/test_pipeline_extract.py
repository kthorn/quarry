"""Tests for extraction pipeline."""

from datetime import datetime

from quarry.models import JobPosting, RawPosting
from quarry.pipeline.extract import (
    detect_remote,
    extract,
    hash_title,
    normalize_location,
    normalize_whitespace,
    strip_html,
)


def test_strip_html_removes_tags():
    html = "<p>This is <strong>bold</strong> text</p>"
    result = strip_html(html)
    assert result == "This is bold text"


def test_strip_html_handles_nested_tags():
    html = "<div><p>Paragraph <span>with <em>emphasis</em></span></p></div>"
    result = strip_html(html)
    assert result == "Paragraph with emphasis"


def test_strip_html_preserves_text_content():
    html = "Plain text without tags"
    result = strip_html(html)
    assert result == "Plain text without tags"


def test_normalize_whitespace_collapses_spaces():
    text = "Multiple   spaces   here"
    result = normalize_whitespace(text)
    assert result == "Multiple spaces here"


def test_normalize_whitespace_collapses_newlines():
    text = "Line one\n\n\nLine two"
    result = normalize_whitespace(text)
    assert result == "Line one\n\nLine two"


def test_normalize_whitespace_strips_leading_trailing():
    text = "  text with spaces  "
    result = normalize_whitespace(text)
    assert result == "text with spaces"


def test_detect_remote_explicit_remote():
    text = "This is a remote position"
    result = detect_remote(text)
    assert result is True


def test_detect_remote_work_from_home():
    text = "Work from home opportunity"
    result = detect_remote(text)
    assert result is True


def test_detect_remote_hybrid():
    text = "Hybrid role - 3 days in office"
    result = detect_remote(text)
    assert result is True


def test_detect_remote_onsite():
    text = "Must be located in San Francisco"
    result = detect_remote(text)
    assert result is None  # No explicit onsite indicator


def test_detect_remote_no_indicator():
    text = "Great engineering role at our company"
    result = detect_remote(text)
    assert result is None


def test_detect_remote_case_insensitive():
    text = "REMOTE position available"
    result = detect_remote(text)
    assert result is True


def test_detect_remote_ignores_remote_in_company_name():
    text = "Remote Inc is hiring for onsite role"
    result = detect_remote(text)
    assert result is False


def test_detect_remote_company_name_without_onsite():
    text = "Remote Inc is hiring engineers"
    result = detect_remote(text)
    # Should detect "remote" in company name as potential false positive
    # but without onsite indicators, returns None (unclear)
    assert result is None


def test_normalize_location_standardizes_us():
    location = "San Francisco, CA, USA"
    result = normalize_location(location)
    assert result == "San Francisco, CA, US"


def test_normalize_location_removes_extra_spaces():
    location = "New  York ,  NY"
    result = normalize_location(location)
    assert result == "New York, NY"


def test_normalize_location_handles_remote():
    location = "Remote - US"
    result = normalize_location(location)
    assert result == "Remote - US"


def test_normalize_location_handles_multiple_locations():
    location = "San Francisco, CA or New York, NY"
    result = normalize_location(location)
    assert result == "San Francisco, CA or New York, NY"


def test_normalize_location_handles_empty():
    result = normalize_location("")
    assert result is None


def test_normalize_location_handles_none():
    result = normalize_location(None)
    assert result is None


def test_normalize_location_standardizes_uk():
    location = "London, UK"
    result = normalize_location(location)
    assert result == "London, United Kingdom"


def test_normalize_location_handles_whitespace_only():
    result = normalize_location("   ")
    assert result is None


def test_hash_title_returns_consistent_hash():
    title = "Senior Software Engineer"
    hash1 = hash_title(title)
    hash2 = hash_title(title)
    assert hash1 == hash2


def test_hash_title_normalizes_case():
    title1 = "Senior Software Engineer"
    title2 = "SENIOR SOFTWARE ENGINEER"
    assert hash_title(title1) == hash_title(title2)


def test_hash_title_normalizes_whitespace():
    title1 = "Senior  Software   Engineer"
    title2 = "Senior Software Engineer"
    assert hash_title(title1) == hash_title(title2)


def test_hash_title_is_sha256():
    title = "Software Engineer"
    result = hash_title(title)
    # SHA256 produces 64 character hex string
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


def test_hash_title_handles_empty():
    result = hash_title("")
    assert result == ""


def test_hash_title_handles_whitespace_only():
    result = hash_title("   ")
    assert result == ""


def test_extract_converts_raw_to_job_posting():
    raw = RawPosting(
        company_id=1,
        title="Senior Software Engineer",
        url="https://example.com/job/123",
        description="<p>Work on <strong>amazing</strong> things</p>",
        location="San Francisco, CA, USA",
        source_type="greenhouse",
    )

    result, _ = extract(raw)

    assert isinstance(result, JobPosting)
    assert result.company_id == 1
    assert result.title == "Senior Software Engineer"
    assert result.url == "https://example.com/job/123"
    assert result.description == "Work on amazing things"
    assert result.location == "San Francisco, CA, US"
    assert result.work_model is None
    assert len(result.title_hash) == 64


def test_extract_detects_remote():
    raw = RawPosting(
        company_id=1,
        title="Remote Software Engineer",
        url="https://example.com/job/456",
        description="This is a remote position working from home",
        location="Remote",
        source_type="greenhouse",
    )

    result, _ = extract(raw)

    assert result.work_model == "remote"


def test_extract_handles_missing_fields():
    raw = RawPosting(
        company_id=1,
        title="Software Engineer",
        url="https://example.com/job/789",
        source_type="lever",
    )

    result, _ = extract(raw)

    assert result.description is None
    assert result.location is None
    assert result.work_model is None


def test_extract_preserves_metadata():
    posted_at = datetime(2024, 1, 15, 10, 30)
    raw = RawPosting(
        company_id=1,
        title="Engineer",
        url="https://example.com/job",
        description="Description",
        posted_at=posted_at,
        source_id="abc123",
        source_type="greenhouse",
    )

    result, _ = extract(raw)

    assert result.posted_at == posted_at
    assert result.source_id == "abc123"
    assert result.source_type == "greenhouse"
