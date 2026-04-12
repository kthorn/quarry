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

from quarry.models import JobPosting, ParseResult, RawPosting
from quarry.pipeline.locations import parse_location


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


def detect_work_model(text: str) -> str | None:
    """Detect work model from job description text.

    Returns 'remote', 'hybrid', 'onsite', or None.
    """
    if not text:
        return None

    text_lower = text.lower()

    onsite_patterns = [
        r"\bon[- ]?site\b",
        r"\bin[- ]?office\b",
        r"\bin office\b",
        r"\brelocation required\b",
    ]

    hybrid_patterns = [
        r"\bhybrid\b",
    ]

    remote_patterns = [
        r"\bremote\b",
        r"\bwork from home\b",
        r"\bwfh\b",
        r"\bfully remote\b",
        r"\b100% remote\b",
        r"\bwork remotely\b",
        r"\bremote-first\b",
        r"\bdistributed team\b",
    ]

    has_onsite = any(re.search(p, text_lower) for p in onsite_patterns)
    has_hybrid = any(re.search(p, text_lower) for p in hybrid_patterns)

    has_remote = any(
        re.search(p, text_lower) for p in remote_patterns if p != r"\bremote\b"
    )
    has_remote_word = (
        re.search(r"\bremote\b(?!\s+(inc|corp|llc|ltd|co|company)\b)", text_lower)
        is not None
    )
    has_remote = has_remote or has_remote_word

    if has_onsite and not has_hybrid and not has_remote:
        return "onsite"
    if has_hybrid:
        return "hybrid"
    if has_remote:
        return "remote"
    return None


def detect_remote(text: str) -> bool | None:
    """Backward-compatible wrapper: detect_work_model → bool.

    Returns True for 'remote' or 'hybrid', False for 'onsite', None for unknown.
    """
    model = detect_work_model(text)
    if model == "onsite":
        return False
    if model in ("remote", "hybrid"):
        return True
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
        Hex string of SHA256 hash, or empty string for empty/whitespace-only titles
    """
    if not title:
        return ""

    # Normalize: lowercase and collapse whitespace
    normalized = re.sub(r"\s+", " ", title.lower().strip())

    if not normalized:
        return ""

    # Hash with SHA256
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def extract(raw: RawPosting) -> tuple[JobPosting, ParseResult]:
    """Extract and transform RawPosting into JobPosting + ParseResult.

    Performs:
    - HTML stripping and text normalization
    - Work model detection
    - Location parsing
    - Title hashing for deduplication

    Args:
        raw: RawPosting from crawler

    Returns:
        Tuple of (JobPosting, ParseResult).
    """
    description = None
    if raw.description:
        description = strip_html(raw.description)

    parse_result = parse_location(raw.location)

    work_model = parse_result.work_model
    if work_model is None:
        combined_text = " ".join(filter(None, [raw.title, description, raw.location]))
        if combined_text:
            work_model = detect_work_model(combined_text)

    location = normalize_location(raw.location)
    title_hash = hash_title(raw.title)

    posting = JobPosting(
        company_id=raw.company_id,
        title=raw.title,
        title_hash=title_hash,
        url=raw.url,
        description=description,
        location=location,
        work_model=work_model,
        posted_at=raw.posted_at,
        source_id=raw.source_id,
        source_type=raw.source_type,
    )

    return posting, parse_result
