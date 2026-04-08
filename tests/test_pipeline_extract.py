"""Tests for extraction pipeline."""

from quarry.pipeline.extract import (
    detect_remote,
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
    assert result is False


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
