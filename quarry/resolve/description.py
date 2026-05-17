"""Company description generation pipeline.

Sources (in order of preference):
1. Wikipedia REST API summary
2. Company website homepage text
3. LLM with company name only (minimal fallback)
"""

import asyncio
import logging
import re

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


def _sanitize_wikipedia_title(company_name: str) -> str:
    """Strip corporate suffixes and replace spaces with underscores."""
    clean = _SUFFIXES.sub("", company_name).strip()
    return clean.replace(" ", "_")


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

    Returns the extract text if found, None otherwise.
    """
    title = _sanitize_wikipedia_title(company_name)
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    try:
        response = httpx.get(
            url,
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "Quarry/0.1"},
        )
        response.raise_for_status()
        data = response.json()
        extract = data.get("extract")
        if extract:
            log.info("Wikipedia hit for %s", company_name)
            return extract.strip()
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
    return description, source
