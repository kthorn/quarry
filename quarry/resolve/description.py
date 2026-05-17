"""Company description generation pipeline.

Sources (in order of preference):
1. Wikipedia REST API summary
2. Company website homepage text
3. LLM with company name only (minimal fallback)
"""

import asyncio
import logging
import re
import threading
import time

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from quarry.llm import LLMError, complete
from quarry.models import Company

log = logging.getLogger(__name__)

_SUFFIXES = re.compile(
    r"\s+(Inc\.?|Ltd\.?|LLC|Corp\.?|PBC|PLC|GmbH|AG|BV|S\.A\.?)$", re.IGNORECASE
)

# Patterns that indicate the LLM refused to answer or couldn't produce a summary
_LLM_REFUSAL = re.compile(
    r"(?:I don'?t have enough|I (?:cannot|can'?t)\s+(?:provide|answer|summarize"
    r"|generate|help)|I(?:'m|\s+am)\s+(?:unable|not able)|Could you provide"
    r"|there (?:is|are) no(?:t enough)?\s+(?:information|details|data|content)"
    r"|not enough (?:information|context)|no (?:meaningful|useful|relevant)"
    r"|unable to (?:provide|generate))",
    re.IGNORECASE,
)

# Cap concurrent Wikipedia API calls to avoid 429 rate limits.
# Wikipedia asks for no more than ~200 req/s, but bursts of even 5–10
# concurrent calls can trigger 429s.  A semaphore of 3 keeps us safe.
_WIKI_SEMAPHORE = threading.BoundedSemaphore(3)

# Time (seconds) between consecutive Wikipedia API calls.
# Enforced at the semaphore level: after releasing, we sleep briefly
# so the next waiter doesn't fire instantly.
_WIKI_COOLDOWN = 0.3


def _sanitize_wikipedia_title(company_name: str) -> str:
    """Strip corporate suffixes and replace spaces with underscores."""
    clean = _SUFFIXES.sub("", company_name).strip()
    return clean.replace(" ", "_")


def _fetch_wikipedia_title(title: str) -> str | None:
    """Fetch Wikipedia summary for a given page title.

    Respects the global semaphore and backoff to avoid 429s.
    Returns the extract text if it's a real article (not a disambiguation
    page), None otherwise.
    """
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"

    _WIKI_SEMAPHORE.acquire()
    try:
        time.sleep(_WIKI_COOLDOWN)
        response = httpx.get(
            url,
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "Quarry/0.1"},
        )
        response.raise_for_status()
        data = response.json()
        if data.get("type") == "disambiguation":
            log.info("Wikipedia disambiguation page for %s, skipping", title)
            return None
        extract = data.get("extract")
        return extract.strip() if extract else None
    finally:
        _WIKI_SEMAPHORE.release()


@retry(
    retry=retry_if_exception_type(
        (
            httpx.HTTPStatusError,
            httpx.ConnectError,
            httpx.TimeoutException,
            httpx.RemoteProtocolError,
        )
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    reraise=True,
)
def fetch_wikipedia_summary(company_name: str) -> str | None:
    """Fetch the Wikipedia summary extract for a company.

    Tries the sanitized company name first, then falls back to
    "<name> (company)" if the bare name is a disambiguation page.
    Returns the extract text if found, None otherwise.
    """
    title = _sanitize_wikipedia_title(company_name)

    try:
        result = _fetch_wikipedia_title(title)
        if result:
            log.info("Wikipedia hit for %s", company_name)
            return result

        # Fallback: try "CompanyName (company)"
        fallback = f"{title}_(company)"
        result = _fetch_wikipedia_title(fallback)
        if result:
            log.info("Wikipedia hit for %s (via '(company)' fallback)", company_name)
            return result

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            log.info("Wikipedia miss for %s", company_name)
            return None
        raise
    return None


def _extract_visible_text(html_text: str) -> str:
    """Extract human-visible text from HTML, stripping scripts/nav/footer."""
    from html.parser import HTMLParser

    class TextExtractor(HTMLParser):
        SKIP_TAGS = {"script", "style", "nav", "footer", "header", "aside", "noscript"}

        def __init__(self) -> None:
            super().__init__()
            self.text_parts: list[str] = []
            self.skip_depth = 0

        def handle_starttag(
            self, tag: str, attrs: list[tuple[str, str | None]]
        ) -> None:
            if tag.lower() in self.SKIP_TAGS:
                self.skip_depth += 1

        def handle_endtag(self, tag: str) -> None:
            if tag.lower() in self.SKIP_TAGS and self.skip_depth > 0:
                self.skip_depth -= 1

        def handle_data(self, data: str) -> None:
            if self.skip_depth == 0:
                self.text_parts.append(data)

    parser = TextExtractor()
    try:
        parser.feed(html_text)
    except Exception:
        log.warning("HTML parsing failed, returning raw text")
        return html_text
    text = " ".join(parser.text_parts)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:4000]


async def _fetch_website_text_async(domain: str) -> str | None:
    """Async fetch and extract visible text from a company's homepage.

    Follows the existing get_client() -> use -> close_client() pattern
    from quarry/resolve/pipeline.py to avoid leaking httpx.AsyncClient
    instances.
    """
    from quarry.http import close_client, get_client

    url = f"https://{domain}"
    try:
        client = get_client()
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()
        text = _extract_visible_text(response.text)
        await close_client()
        return text
    except Exception as e:
        await close_client()
        log.warning("Website fetch failed for %s: %s", domain, e)
        return None


def fetch_website_text(domain: str) -> str | None:
    """Sync wrapper for website text fetch.

    Uses asyncio.run() to bridge sync context. Each call creates a fresh
    event loop, so get_client() will create a new AsyncClient - the async
    function calls close_client() to clean it up before returning.
    """
    return asyncio.run(_fetch_website_text_async(domain))


def _build_prompt(company_name: str, source_text: str) -> str:
    """Build the LLM prompt for company description summarization."""
    return (
        f"Summarize what {company_name} does in 2-3 concise sentences.\n"
        "This summary helps a job seeker decide whether to prioritize applying there.\n"
        "Be factual and neutral. Do not include marketing language.\n\n"
        "Source material:\n"
        f"{source_text}"
    )


def generate_company_description(company: Company) -> tuple[str, str]:
    """Generate a description for a company via Wikipedia -> website -> LLM.

    Returns:
        tuple of (description, source) where source is one of:
        'wikipedia', 'website', or raises LLMError on total failure.
    """
    # Step 1: Try Wikipedia
    wiki_text = fetch_wikipedia_summary(company.name)
    if wiki_text:
        source = "wikipedia"
        prompt_text = wiki_text
    else:
        # Step 2: Try website
        website_text = None
        if company.domain:
            website_text = fetch_website_text(company.domain)
        if website_text:
            source = "website"
            prompt_text = website_text
        else:
            # Step 3: Minimal fallback - company name only
            source = "pending"
            prompt_text = company.name

    prompt = _build_prompt(company.name, prompt_text)
    try:
        result = complete(prompt)
    except LLMError:
        log.error("LLM failed for %s, leaving description pending", company.name)
        raise

    description = result.strip()[:500]

    # Guard against LLM refusals (e.g. "I don't have enough information…")
    if _LLM_REFUSAL.search(description):
        log.warning("LLM refused to summarize %s, using minimal fallback", company.name)
        description = f"{company.name} is a company."
        source = "pending"

    return description, source
