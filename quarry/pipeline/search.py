import re

import numpy as np

from quarry.models import JobPosting


def match_keywords(text: str, keywords: list[str]) -> list[str]:
    """Find which keywords match the text using whole-word, case-insensitive search.

    Uses lookbehind/lookahead instead of \\b to correctly handle keywords
    containing non-word characters (e.g. "C++").

    Args:
        text: Text to search within.
        keywords: List of keywords to look for.

    Returns:
        List of keywords that were found in the text.
    """
    found = []
    for word in keywords:
        escaped = re.escape(word)
        if re.search(rf"(?<!\w){escaped}(?!\w)", text, re.IGNORECASE):
            found.append(word)
    return found


def filter_by_keywords(
    postings: list[tuple[JobPosting, str]],
    must_have_title: list[str] | None = None,
    must_have_description: list[str] | None = None,
) -> list[tuple[JobPosting, str, list[str], list[str]]]:
    """Filter postings by keyword presence in title and/or description.

    Within each keyword list, ANY match passes (OR). Between the two lists,
    both conditions must be met (AND) if both are specified.

    Args:
        postings: List of (JobPosting, company_name) tuples.
        must_have_title: Keywords to match in title (OR within list).
        must_have_description: Keywords to match in description (OR within list).

    Returns:
        List of (JobPosting, company_name, matched_title_keywords,
        matched_description_keywords) tuples.
    """
    results = []
    for posting, company_name in postings:
        title = posting.title or ""
        description = posting.description or ""

        matched_title = (
            match_keywords(title, must_have_title) if must_have_title else []
        )
        matched_desc = (
            match_keywords(description, must_have_description)
            if must_have_description
            else []
        )

        title_passes = len(matched_title) > 0 if must_have_title is not None else True
        desc_passes = (
            len(matched_desc) > 0 if must_have_description is not None else True
        )

        if title_passes and desc_passes:
            results.append((posting, company_name, matched_title, matched_desc))
    return results


def score_postings(
    postings: list[tuple[JobPosting, str, list[str], list[str]]],
    ideal_embedding: np.ndarray,
    dim: int,
) -> list[dict]:
    """Score postings against an ideal embedding and return sorted results.

    Args:
        postings: Filtered postings from filter_by_keywords.
        ideal_embedding: The ideal role embedding vector.
        dim: Expected embedding dimension.

    Returns:
        List of result dicts sorted by similarity descending.
    """
    from quarry.pipeline.embedder import deserialize_embedding
    from quarry.pipeline.filter import cosine_similarity

    results = []
    for posting, company_name, matched_title, matched_desc in postings:
        if posting.embedding is None:
            continue

        embedding = deserialize_embedding(posting.embedding, dim)
        score = cosine_similarity(embedding, ideal_embedding)
        results.append(
            {
                "title": posting.title,
                "company": company_name,
                "score": round(score, 4),
                "matched_title": matched_title,
                "matched_desc": matched_desc,
            }
        )

    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def format_results(
    results: list[dict],
    has_score: bool,
    has_title_keywords: bool,
    has_desc_keywords: bool,
    limit: int,
    min_score: float = 0.0,
) -> str:
    """Format search results as a terminal table.

    Args:
        results: Scored or unscored result dicts.
        has_score: Whether similarity scores are present.
        has_title_keywords: Whether to show matched title keywords.
        has_desc_keywords: Whether to show matched description keywords.
        limit: Maximum rows to display.
        min_score: Minimum similarity score to include.

    Returns:
        Formatted table string.
    """
    from tabulate import tabulate

    if has_score:
        results = [r for r in results if r["score"] >= min_score]

    results = results[:limit]

    if not results:
        return "No results found."

    headers = ["#"]
    if has_score:
        headers.append("Score")
    headers.append("Title")
    headers.append("Company")
    if has_title_keywords:
        headers.append("Matched Title KW")
    if has_desc_keywords:
        headers.append("Matched Desc KW")

    rows: list[list[str | int]] = []
    for i, r in enumerate(results, 1):
        row: list[str | int] = [i]
        if has_score:
            row.append(f"{r['score']:.4f}")
        row.append(r["title"])
        row.append(r["company"])
        if has_title_keywords:
            row.append(", ".join(r["matched_title"]) if r["matched_title"] else "-")
        if has_desc_keywords:
            row.append(", ".join(r["matched_desc"]) if r["matched_desc"] else "-")
        rows.append(row)

    table = tabulate(rows, headers=headers, tablefmt="simple")
    count_msg = f"\nShowing {len(results)} result(s)."
    return table + count_msg
