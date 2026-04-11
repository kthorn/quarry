import logging
import re
from typing import Literal
from urllib.parse import urlparse

import httpx

from quarry.models import Company

log = logging.getLogger(__name__)

ATSType = Literal["greenhouse", "lever", "ashby", "generic", "unknown"]

ATS_URL_PATTERNS: list[tuple[ATSType, re.Pattern]] = [
    ("greenhouse", re.compile(r"https?://boards\.greenhouse\.io/([^/?#]+)")),
    (
        "greenhouse",
        re.compile(r"https?://boards-api\.greenhouse\.io/v1/boards/([^/?#]+)"),
    ),
    ("lever", re.compile(r"https?://jobs\.lever\.co/([^/?#]+)")),
    ("ashby", re.compile(r"https?://jobs\.ashbyhq\.com/([^/?#]+)")),
]

HTML_SIGNATURES: dict[ATSType, list[str]] = {
    "greenhouse": ["boards.greenhouse.io", "greenhouse.io/embed"],
    "lever": ["jobs.lever.co", "lever.co/embed"],
    "ashby": ["jobs.ashbyhq.com", "ashbyhq.com/embed"],
}


def detect_ats_url_patterns(url: str) -> tuple[ATSType, str | None]:
    for ats_type, pattern in ATS_URL_PATTERNS:
        match = pattern.search(url)
        if match:
            return ats_type, match.group(1)
    return "unknown", None


async def detect_ats(
    company: Company, client: httpx.AsyncClient | None = None, html: str | None = None
) -> tuple[ATSType, str | None]:
    if company.ats_type not in ("unknown",) and company.ats_type is not None:
        return company.ats_type, company.ats_slug

    if not company.careers_url:
        return "unknown", None

    ats_type, slug = detect_ats_url_patterns(company.careers_url)
    if ats_type != "unknown":
        log.info(
            "ATS detected via URL pattern for %s: %s/%s", company.name, ats_type, slug
        )
        return ats_type, slug

    if html is None:
        try:
            from quarry.http import get_client

            if client is None:
                client = get_client()
            response = await client.get(company.careers_url, timeout=5.0)
            if response.status_code != 200:
                log.warning(
                    "HTML fetch failed for %s: status %d",
                    company.name,
                    response.status_code,
                )
                return "unknown", None
            html = response.text
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            log.warning("HTML fetch error for %s: %s", company.name, e)
            return "unknown", None

    html_lower = html.lower()
    for ats_type, signatures in HTML_SIGNATURES.items():
        for sig in signatures:
            if sig in html_lower:
                slug = _extract_slug_from_html(ats_type, html, company.careers_url)
                log.info(
                    "ATS detected via HTML for %s: %s/%s", company.name, ats_type, slug
                )
                return ats_type, slug

    return "generic", None


def _extract_slug_from_html(ats_type: str, html: str, url: str) -> str | None:
    patterns = {
        "greenhouse": re.compile(r"boards\.greenhouse\.io/([^\"'\s?#]+)"),
        "lever": re.compile(r"jobs\.lever\.co/([^\"'\s?#]+)"),
        "ashby": re.compile(r"jobs\.ashbyhq\.com/([^\"'\s?#]+)"),
    }
    pattern = patterns.get(ats_type)
    if pattern:
        match = pattern.search(html)
        if match:
            return match.group(1)
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) >= 1 and parts[0]:
        return parts[0]
    return None
