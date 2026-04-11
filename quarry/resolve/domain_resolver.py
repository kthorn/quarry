import logging
import re

import httpx

from quarry.models import Company

log = logging.getLogger(__name__)

SUFFIXES_TO_STRIP = [
    "inc.",
    "inc",
    "llc",
    "ltd.",
    "ltd",
    "co.",
    "co",
    "corp.",
    "corp",
    "group",
    "holdings",
    "company",
    "companies",
]

SUFFIX_RE = re.compile(
    r"\s+(?:inc\.?|llc|ltd\.?|co\.?|corp\.?|group|holdings|company|companies)\s*$",
    re.IGNORECASE,
)


def normalize_name(name: str) -> str:
    name = name.strip().lower()
    prev = None
    while name != prev:
        prev = name
        name = SUFFIX_RE.sub("", name).strip()
    if name.endswith(".com"):
        name = name[:-4]
    return name


async def resolve_domain(
    company: Company, client: httpx.AsyncClient | None = None
) -> str | None:
    if company.domain:
        return company.domain

    from quarry.http import get_client

    if client is None:
        client = get_client()

    normalized = normalize_name(company.name)
    if not normalized:
        return None

    candidates = _generate_candidates(normalized)

    for domain in candidates:
        try:
            response = await client.head(f"https://{domain}", timeout=10.0)
            if response.status_code < 400:
                log.info("Resolved domain for %s: %s", company.name, domain)
                return domain
        except (httpx.RequestError, httpx.HTTPStatusError):
            continue

    log.warning("Could not resolve domain for %s", company.name)
    return None


def _generate_candidates(normalized: str) -> list[str]:
    candidates = []
    base = re.sub(r"\s+", "", normalized) + ".com"
    candidates.append(base)

    if " " in normalized:
        hyphenated = normalized.replace(" ", "-") + ".com"
        candidates.append(hyphenated)

        words = normalized.split()
        if len(words) > 1:
            first_word = words[0]
            candidates.append(first_word + ".com")

    return candidates
