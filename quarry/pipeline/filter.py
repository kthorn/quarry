"""Similarity filtering and keyword blocklist for job postings.

Scores postings against the ideal role embedding using cosine similarity,
then applies a keyword blocklist to reject irrelevant postings.
"""

import logging

import numpy as np

from quarry.models import FilterResult, RawPosting
from quarry.pipeline.embedder import embed_posting

log = logging.getLogger(__name__)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        a: First vector.
        b: Second vector.

    Returns:
        Cosine similarity in [-1, 1]. Returns 0.0 if either vector is zero.
    """
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def score_similarity(
    posting_embedding: np.ndarray, ideal_embedding: np.ndarray
) -> float:
    """Score a posting's relevance against the ideal role embedding.

    Args:
        posting_embedding: Embedding of the job posting.
        ideal_embedding: Embedding of the ideal role description.

    Returns:
        Cosine similarity score in [-1, 1]. Higher = more relevant.
    """
    return cosine_similarity(posting_embedding, ideal_embedding)


def apply_keyword_blocklist(posting: RawPosting, blocklist: list[str]) -> bool:
    """Check if a posting passes the keyword blocklist.

    A posting fails if any blocklisted phrase appears as a case-insensitive
    substring in the title, description, or location.

    Args:
        posting: RawPosting to check.
        blocklist: List of keyword phrases to reject.

    Returns:
        True if the posting passes (no blocklisted keywords found),
        False if it should be filtered out.
    """
    if not blocklist:
        return True

    text = " ".join(
        filter(None, [posting.title, posting.description, posting.location])
    ).lower()

    for phrase in blocklist:
        if phrase.lower() in text:
            log.debug("Blocklisted posting '%s': matched '%s'", posting.title, phrase)
            return False

    return True


def filter_posting(
    posting: RawPosting,
    ideal_embedding: np.ndarray,
    threshold: float | None = None,
    blocklist: list[str] | None = None,
) -> FilterResult:
    """Filter a single posting through similarity scoring and blocklist.

    Pipeline: embed posting → score similarity → check blocklist → return result.

    The similarity score is always computed and included in the result,
    even if the posting is blocked. Blocked postings get skip_reason set.

    Args:
        posting: RawPosting to evaluate.
        ideal_embedding: Embedding of the ideal role description.
        threshold: Minimum cosine similarity to pass. If None, reads from
                   config settings (default 0.58 in config.yaml).
        blocklist: Keyword phrases that cause rejection.

    Returns:
        FilterResult with pass/fail status, skip reason, and similarity score.
    """
    if threshold is None:
        from quarry.config import settings

        threshold = settings.similarity_threshold
    blocklist = blocklist or []

    posting_embedding = embed_posting(posting)
    similarity = score_similarity(posting_embedding, ideal_embedding)

    if not apply_keyword_blocklist(posting, blocklist):
        return FilterResult(
            posting=posting,
            passed=False,
            skip_reason="blocklist",
            similarity_score=round(similarity, 4),
        )

    if similarity < threshold:
        return FilterResult(
            posting=posting,
            passed=False,
            skip_reason="low_similarity",
            similarity_score=round(similarity, 4),
        )

    return FilterResult(
        posting=posting,
        passed=True,
        skip_reason=None,
        similarity_score=round(similarity, 4),
    )
