"""Extraction pipeline: RawPosting → JobPosting transformation.

This module handles:
- HTML tag stripping and whitespace normalization
- Remote work detection via keyword heuristics
- Location string normalization
- Title hashing for deduplication
"""

import re

from bs4 import BeautifulSoup


def strip_html(html: str) -> str:
    """Remove HTML tags and return plain text.

    Args:
        html: HTML string to strip

    Returns:
        Plain text with HTML tags removed and whitespace normalized
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ")
    return normalize_whitespace(text)


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace in text.

    Collapses multiple spaces to single space, multiple newlines to double newlines,
    and strips leading/trailing whitespace.

    Args:
        text: Text to normalize

    Returns:
        Normalized text
    """
    if not text:
        return ""
    # Collapse multiple spaces to single space
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse 3+ newlines to 2 newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip leading/trailing whitespace
    text = text.strip()
    return text


def detect_remote(text: str) -> bool | None:
    """Detect if a job posting is remote using keyword heuristics.

    Returns True if remote indicators found, False if onsite indicators found,
    None if no clear indicators.

    Args:
        text: Job description text to analyze

    Returns:
        True if remote, False if onsite, None if unclear
    """
    if not text:
        return None

    text_lower = text.lower()

    # Hybrid indicators (always counts as remote, check first)
    hybrid_patterns = [
        r"\bhybrid\b",
        r"\bremote-first\b",
        r"\bdistributed team\b",
    ]

    # Check hybrid first - always counts as remote
    if any(re.search(p, text_lower) for p in hybrid_patterns):
        return True

    # Remote indicators (strong)
    remote_patterns = [
        r"\bremote\b",
        r"\bwork from home\b",
        r"\bwfh\b",
        r"\bfully remote\b",
        r"\b100% remote\b",
        r"\bwork remotely\b",
    ]

    # Onsite indicators (strong office requirement)
    onsite_patterns = [
        r"\bon[- ]?site\b",
        r"\bin[- ]?office\b",
        r"\bin office\b",
        r"\brelocation required\b",
        r"\bno remote\b",
        r"\bnot remote\b",
        r"\bmust (be )?(located|based) in\b",
    ]

    # Check for remote indicators
    has_remote = any(re.search(p, text_lower) for p in remote_patterns)
    has_onsite = any(re.search(p, text_lower) for p in onsite_patterns)

    # Check if "remote" appears to be in a company name (potential false positive)
    has_company_name = re.search(
        r"\bremote\s+(inc|corp|llc|ltd|co|company)\b", text_lower
    )

    # If "remote" is only in company name and no other indicators, unclear
    if has_company_name and not has_onsite:
        return None

    # If both remote and onsite present, prefer onsite (more specific)
    if has_remote and has_onsite:
        return False
    # If remote found
    if has_remote:
        return True
    # If onsite found
    if has_onsite:
        return False

    return None

    text_lower = text.lower()

    # Remote indicators (strong)
    remote_patterns = [
        r"\bremote\b",
        r"\bwork from home\b",
        r"\bwfh\b",
        r"\bfully remote\b",
        r"\b100% remote\b",
        r"\bwork remotely\b",
    ]

    # Hybrid indicators (counts as remote)
    hybrid_patterns = [
        r"\bhybrid\b",
        r"\bremote-first\b",
        r"\bdistributed team\b",
    ]

    # Onsite indicators (strong office requirement)
    onsite_patterns = [
        r"\bon[- ]?site\b",
        r"\bin[- ]?office\b",
        r"\bin office\b",
        r"\brelocation required\b",
        r"\bno remote\b",
        r"\bnot remote\b",
    ]

    # Location constraint indicators (not necessarily onsite)
    location_constraint_patterns = [
        r"\bmust (be )?(located|based) in\b",
    ]

    # Check for remote indicators
    has_remote = any(
        re.search(p, text_lower) for p in remote_patterns + hybrid_patterns
    )
    has_onsite = any(re.search(p, text_lower) for p in onsite_patterns)
    has_location_constraint = any(
        re.search(p, text_lower) for p in location_constraint_patterns
    )

    # If both remote and onsite present, prefer onsite (more specific)
    if has_remote and has_onsite:
        return False
    # If remote with location constraint, still remote (e.g., "Remote, must be based in US")
    if has_remote:
        return True
    # If only onsite indicators, mark as onsite
    if has_onsite:
        return False
    # Location constraint alone is not enough to determine onsite
    if has_location_constraint:
        return None

    return None
