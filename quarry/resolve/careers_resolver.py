import logging

import httpx

from quarry.models import Company

log = logging.getLogger(__name__)

JOB_KEYWORDS = {"job", "career", "position", "opening", "apply", "opportunit"}

URL_PATTERNS = [
    "/careers",
    "/jobs",
    "/careers/search",
    "/about/careers",
    "/en/careers",
]


async def resolve_careers_url(
    company: Company, client: httpx.AsyncClient | None = None
) -> str | None:
    if company.careers_url:
        return company.careers_url

    if not company.domain:
        return None

    from quarry.http import get_client

    if client is None:
        client = get_client()

    domains = [company.domain]
    if not company.domain.startswith("www."):
        domains.append(f"www.{company.domain}")

    for domain in domains:
        for path in URL_PATTERNS:
            url = f"https://{domain}{path}"
            result = await _probe_url(client, url)
            if result:
                log.info("Resolved careers URL for %s: %s", company.name, result)
                return result

    log.warning("Could not resolve careers URL for %s", company.name)
    return None


async def _probe_url(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        response = await client.get(url, timeout=5.0)
        if response.status_code != 200:
            return None
        text = response.text.lower()
        if any(kw in text for kw in JOB_KEYWORDS):
            return str(response.url)
        return None
    except (httpx.RequestError, httpx.HTTPStatusError):
        return None
