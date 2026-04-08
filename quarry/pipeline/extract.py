"""Extraction pipeline: RawPosting → JobPosting transformation.

This module handles:
- HTML tag stripping and whitespace normalization
- Remote work detection via keyword heuristics
- Location string normalization
- Title hashing for deduplication
"""

import hashlib
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

    # Check for onsite indicators
    has_onsite = any(re.search(p, text_lower) for p in onsite_patterns)

    # Check for remote indicators, excluding "remote" in company name context
    has_other_remote = any(
        re.search(p, text_lower) for p in remote_patterns if p != r"\bremote\b"
    )
    has_remote_excluding_company = (
        re.search(r"\bremote\b(?!\s+(inc|corp|llc|ltd|co|company)\b)", text_lower)
        is not None
    )
    has_remote = has_remote_excluding_company or has_other_remote

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


def normalize_location(location: str | None) -> str | None:
    """Normalize location string.

    Standardizes country codes, removes extra whitespace, and handles common patterns.

    Args:
        location: Location string to normalize

    Returns:
        Normalized location string or None if empty
    """
    if not location:
        return None

    # Strip and collapse whitespace
    location = re.sub(r"\s+", " ", location.strip())

    # Standardize country codes
    location = re.sub(r"\bUSA?\b", "US", location, flags=re.IGNORECASE)
    location = re.sub(r"\bUK\b", "United Kingdom", location, flags=re.IGNORECASE)

    # Remove extra spaces around commas
    location = re.sub(r"\s*,\s*", ", ", location)

    return location if location else None


def hash_title(title: str) -> str:
    """Create a hash of job title for deduplication.

    Normalizes title (lowercase, collapse whitespace) before hashing.
    Uses SHA256 for collision resistance.

    Args:
        title: Job title to hash

    Returns:
        Hex string of SHA256 hash
    """
    if not title:
        return ""

    # Normalize: lowercase and collapse whitespace
    normalized = re.sub(r"\s+", " ", title.lower().strip())

    # Hash with SHA256
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
