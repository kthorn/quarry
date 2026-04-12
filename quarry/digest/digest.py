"""Build and write digest of new job postings.

Reads new postings from DB, sorts by similarity, formats as plain text,
and writes to a file. Marks included postings as 'seen'.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

from quarry.config import settings
from quarry.store.db import Database

log = logging.getLogger(__name__)


def build_digest(db: Database, limit: int | None = None) -> list[dict]:
    """Fetch new postings sorted by similarity score.

    Args:
        db: Database instance.
        limit: Maximum postings to include. Defaults to config digest_top_n.

    Returns:
        List of dicts with posting data, sorted by similarity_score descending.
    """
    limit = limit or settings.digest_top_n
    postings = db.get_recent_postings(limit=limit, status="new")
    entries = []
    for p in postings:
        company_name = db.get_company_name(p.company_id) or "Unknown"
        entries.append(
            {
                "id": p.id,
                "company_name": company_name,
                "title": p.title,
                "url": p.url,
                "similarity_score": p.similarity_score or 0.0,
                "location": p.location or "N/A",
                "work_model": p.work_model,
            }
        )
    return entries


def format_digest(entries: list[dict]) -> str:
    """Format digest entries as plain text.

    Args:
        entries: List of posting dicts from build_digest.

    Returns:
        Formatted plain text digest string.
    """
    if not entries:
        return "No new job postings found.\n"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"=== Quarry Digest - {now} ===",
        f"{len(entries)} new posting(s)\n",
    ]

    for i, e in enumerate(entries, 1):
        wm = e.get("work_model")
        work_tag = f" [{wm.title()}]" if wm else ""
        score_tag = f" (score: {e['similarity_score']:.3f})"
        lines.append(f"{i}. {e['title']} at {e['company_name']}{work_tag}{score_tag}")
        lines.append(f"   {e['location']}")
        lines.append(f"   {e['url']}")
        lines.append("")

    return "\n".join(lines)


def write_digest(entries: list[dict], output_path: str | None = None) -> str:
    """Write formatted digest to a file.

    Args:
        entries: List of posting dicts from build_digest.
        output_path: File path to write to. Defaults to `digest_<timestamp>.txt` in cwd.

    Returns:
        Path to the written file.
    """
    if output_path is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        output_path = f"digest_{timestamp}.txt"

    text = format_digest(entries)
    Path(output_path).write_text(text)
    log.info("Digest written to %s", output_path)

    return output_path


def mark_digest_seen(db: Database, entries: list[dict]) -> None:
    """Mark all digest entries as seen in the database.

    Args:
        db: Database instance.
        entries: List of posting dicts from build_digest.
    """
    posting_ids = [e["id"] for e in entries]
    db.mark_postings_seen(posting_ids)
    log.info("Marked %d postings as seen", len(posting_ids))
