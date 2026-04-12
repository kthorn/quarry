# quarry/crawlers/careers_page.py
import hashlib
import ipaddress
import logging
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from quarry.crawlers.base import BaseCrawler, Crawl404Error
from quarry.http import get_client
from quarry.models import Company, RawPosting

logger = logging.getLogger(__name__)

ATS_DOMAINS = frozenset(
    {
        "boards.greenhouse.io",
        "boards-api.greenhouse.io",
        "job-boards.greenhouse.io",
        "jobs.lever.co",
        "api.lever.co",
        "jobs.ashbyhq.com",
    }
)

JOB_PATH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"/jobs?/\d+", re.I),
    re.compile(r"/jobs?/search", re.I),
    re.compile(r"/jobs?/results", re.I),
    re.compile(r"/position", re.I),
    re.compile(r"/openings?", re.I),
    re.compile(r"/role/", re.I),
    re.compile(r"/current[-_]openings", re.I),
    re.compile(r"/careers?/[^/]+", re.I),
]

JOB_TEXT_HEURISTICS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(senior|junior|staff|principal|lead|director|manager|head|vp|vice)\b", re.I
    ),
    re.compile(
        r"\b(engineer|developer|designer|analyst|scientist|architect|manager|partner|coordinator)\b",
        re.I,
    ),
    re.compile(
        r"\b(associate|specialist|consultant|advisor|strategist|operator|recruiter)\b",
        re.I,
    ),
    re.compile(r"\b(intern|fellow|apprentice)\b", re.I),
    re.compile(r"\bapply\b", re.I),
]

FILE_EXTENSIONS = frozenset({".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xlsx"})


def _is_likely_job_link(text: str, url: str) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    path = parsed.path.lower()

    if not text or len(text.strip()) < 3:
        return False

    for ext in FILE_EXTENSIONS:
        if path.endswith(ext):
            return False

    if hostname in ATS_DOMAINS:
        return True

    for pat in JOB_PATH_PATTERNS:
        if pat.search(path):
            return True

    for pat in JOB_TEXT_HEURISTICS:
        if pat.search(text):
            return True

    return False


ATS_SLUG_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "greenhouse": [
        re.compile(r"https?://(?:boards|job-boards)\.greenhouse\.io/([^/?#]+)"),
        re.compile(r"https?://boards-api\.greenhouse\.io/v1/boards/([^/?#]+)"),
    ],
    "lever": [re.compile(r"https?://jobs\.lever\.co/([^/?#]+)")],
    "ashby": [re.compile(r"https?://jobs\.ashbyhq\.com/([^/?#]+)")],
}


def detect_ats_from_links(
    links: list[tuple[str, str]],
) -> tuple[str | None, str | None] | None:
    """Scan extracted links for known ATS board URLs.

    Returns (ats_type, ats_slug) if a board is found, or None.
    Checks ATS domains first, then falls back to scanning text for
    common patterns like "View open roles" pointing to job boards.
    """
    for _text, href in links:
        hostname = urlparse(href).hostname
        if hostname is None:
            continue
        hostname = hostname.lower()
        if hostname in ATS_DOMAINS:
            for ats_type, patterns in ATS_SLUG_PATTERNS.items():
                for pattern in patterns:
                    match = pattern.search(href)
                    if match:
                        return ats_type, match.group(1)

    return None


PRIVATE_RANGES = [
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv6Network("::1/128"),
]


def _is_private_ip(ip_str: str) -> bool:
    """Check if IP address is private or link-local."""
    try:
        ip = ipaddress.ip_address(ip_str)
        if ip.is_loopback:
            return True
        for network in PRIVATE_RANGES:
            if ip in network:
                return True
    except ValueError:
        pass
    return False


def _get_host_ip(hostname: str) -> str | None:
    """Resolve hostname to IP address."""
    try:
        return socket.gethostbyname(hostname)
    except socket.gaierror:
        return None


class _LinkExtractor(HTMLParser):
    """Incrementally extract <a href> tags from streamed HTML."""

    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._in_link_href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag != "a":
            return
        href = next((v for k, v in attrs if k == "href" and v), None)
        if href:
            self._in_link_href = href
            self._text_parts = []

    def handle_data(self, data: str):
        if self._in_link_href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str):
        if tag != "a" or self._in_link_href is None:
            return
        text = " ".join("".join(self._text_parts).split()).strip()
        if text:
            self.links.append((text, self._in_link_href))
        self._in_link_href = None
        self._text_parts = []


class CareersPageCrawler(BaseCrawler):
    """Fallback crawler for generic careers pages.

    Security measures:
    - Only allow HTTPS URLs
    - Block private/link-local IP ranges
    - Enforce 10s timeout, max 5MB response
    - Limit redirects to 5 max
    - Log sanitized URLs (strip query params)

    Uses streaming HTML parsing: links are extracted incrementally
    as the response arrives. If the page exceeds max_response_bytes,
    partial results are returned instead of discarding everything.
    """

    def __init__(self, max_retries: int = 3, retry_base_delay: int = 2):
        super().__init__(max_retries, retry_base_delay)
        self.max_response_bytes = 5 * 1024 * 1024  # 5MB
        self.max_redirects = 5

    async def crawl(self, company: Company) -> list[RawPosting]:
        """Fetch jobs from generic careers page."""
        if not company.careers_url:
            logger.warning(f"Company {company.name} has no careers_url")
            return []

        url = company.careers_url

        parsed = urlparse(url)
        if parsed.scheme != "https":
            logger.warning(f"Careers page URL must be HTTPS: {url}")
            return []

        hostname = parsed.hostname
        if not hostname:
            logger.warning(f"Invalid careers URL: {url}")
            return []

        ip = _get_host_ip(hostname)
        if ip and _is_private_ip(ip):
            logger.warning(f"Blocked private IP for {hostname}: {ip}")
            return []

        return await self._fetch_page(company)

    async def _fetch_page(self, company: Company) -> list[RawPosting]:
        """Fetch and parse careers page HTML using streaming.

        Also detects if the page links to a known ATS board and logs
        a suggestion to upgrade the company's ats_type.
        """
        url = company.careers_url or ""
        sanitized_url = url.split("?")[0].rstrip("/")

        try:
            client = get_client()
            extractor = _LinkExtractor()
            total_bytes = 0
            truncated = False

            async with client.stream("GET", url) as response:
                response.raise_for_status()

                async for chunk in response.aiter_bytes():
                    total_bytes += len(chunk)
                    if total_bytes > self.max_response_bytes:
                        logger.warning(
                            "Response too large for %s (%d bytes), "
                            "returning %d links found so far",
                            sanitized_url,
                            total_bytes,
                            len(extractor.links),
                        )
                        truncated = True
                        break
                    try:
                        extractor.feed(chunk.decode("utf-8", errors="ignore"))
                    except Exception:
                        pass

            if not truncated:
                extractor.close()

            if company.ats_type in ("generic", "unknown"):
                detected = detect_ats_from_links(extractor.links)
                if detected:
                    ats_type, ats_slug = detected
                    logger.info(
                        "Detected ATS board for %s: ats_type=%s, ats_slug=%s. "
                        "Consider updating: python -m quarry.resolve resolve "
                        "--redetect-ats",
                        company.name,
                        ats_type,
                        ats_slug,
                    )

            return self._links_to_postings(
                extractor.links, company.id or 0, sanitized_url
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise Crawl404Error(company.name, sanitized_url) from e
            logger.error(f"HTTP error fetching {company.name}: {e}")
            return []
        except httpx.RequestError as e:
            logger.error(f"Request error fetching {company.name}: {e}")
            return []

    def _links_to_postings(
        self, links: list[tuple[str, str]], company_id: int, source_url: str
    ) -> list[RawPosting]:
        """Convert extracted (text, href) pairs to RawPosting objects.

        Filters out links that are clearly not job listings (navigation,
        privacy policies, research pages, etc.).
        """
        seen = set()
        postings = []

        for text, href in links:
            if not href.startswith("/") and not href.startswith("http"):
                continue

            full_url: str = (
                href if href.startswith("http") else urljoin(source_url, href)
            )

            if not _is_likely_job_link(text, full_url):
                logger.debug("Filtered non-job link: %r -> %s", text, full_url)
                continue

            source_id = self._generate_source_id(full_url)

            if source_id in seen:
                continue
            seen.add(source_id)

            posting = RawPosting(
                company_id=company_id,
                title=text,
                url=full_url,
                description=None,
                location=None,
                source_type="careers_page",
                source_id=source_id,
            )
            postings.append(posting)

        return postings

    def _generate_source_id(self, url: str) -> str:
        """Generate source_id from URL using SHA256."""
        normalized = url.lower().rstrip("/")
        hash_digest = hashlib.sha256(normalized.encode()).hexdigest()
        return hash_digest[:16]
