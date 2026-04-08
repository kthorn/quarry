"""Tests for extraction pipeline."""

from quarry.pipeline.extract import normalize_whitespace, strip_html


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
