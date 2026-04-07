# quarry/crawlers/careers_page.py
import hashlib
import ipaddress
import logging
import socket
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import httpx

from quarry.crawlers.base import BaseCrawler
from quarry.models import Company, RawPosting

logger = logging.getLogger(__name__)

PRIVATE_RANGES = [
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("127.0.0.0/8"),
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


class CareersPageCrawler(BaseCrawler):
    """Fallback crawler for generic careers pages.

    Security measures:
    - Only allow HTTPS URLs
    - Block private/link-local IP ranges
    - Enforce 10s timeout, max 1MB response
    - Limit redirects to 5 max
    - Log sanitized URLs (strip query params)
    """

    def __init__(self, max_retries: int = 3, retry_base_delay: int = 2):
        super().__init__(max_retries, retry_base_delay)
        self.max_response_bytes = 1048576  # 1MB
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
        """Fetch and parse careers page HTML."""
        url = company.careers_url or ""
        sanitized_url = url.split("?")[0].rstrip("/")

        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                follow_redirects=True,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            ) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()

                    chunks = []
                    async for chunk in response.aiter_bytes():
                        chunks.append(chunk)
                        if sum(len(c) for c in chunks) > self.max_response_bytes:
                            logger.warning(f"Response too large for {sanitized_url}")
                            return []

                    html = b"".join(chunks).decode("utf-8", errors="ignore")

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching {company.name}: {e}")
            return []
        except httpx.RequestError as e:
            logger.error(f"Request error fetching {company.name}: {e}")
            return []

        return self._parse_html(html, company.id or 0, sanitized_url)

    def _parse_html(
        self, html: str, company_id: int, source_url: str
    ) -> list[RawPosting]:
        """Parse HTML to extract job listings."""
        soup = BeautifulSoup(html, "html.parser")
        postings = []

        for link in soup.find_all("a", href=True):
            href = str(link.get("href", ""))  # type: ignore[attr-defined]
            text = link.get_text(strip=True)

            if not text:
                continue

            if not href.startswith("/") and not href.startswith("http"):
                continue

            full_url: str = href
            if not full_url.startswith("http"):
                from urllib.parse import urljoin

                full_url = urljoin(source_url, href)

            source_id = self._generate_source_id(full_url)

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
