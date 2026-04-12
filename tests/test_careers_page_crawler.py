import pytest

from quarry.crawlers.careers_page import (
    CareersPageCrawler,
    _is_likely_job_link,
    _LinkExtractor,
    detect_ats_from_links,
)
from quarry.models import Company


@pytest.fixture
def company():
    return Company(
        id=4,
        name="Test Corp",
        ats_type="unknown",
        careers_url="https://example.com/careers",
    )


@pytest.mark.asyncio
async def test_careers_page_rejects_http_not_https():
    crawler = CareersPageCrawler()
    company = Company(id=1, name="Test", careers_url="http://example.com/careers")

    postings = await crawler.crawl(company)
    assert postings == []


@pytest.mark.asyncio
async def test_careers_page_rejects_private_ip():
    crawler = CareersPageCrawler()
    company = Company(id=1, name="Test", careers_url="http://192.168.1.1/careers")

    postings = await crawler.crawl(company)
    assert postings == []


class TestLinkExtractor:
    def test_extracts_simple_links(self):
        html = '<a href="/jobs/1">Software Engineer</a>'
        extractor = _LinkExtractor()
        extractor.feed(html)
        extractor.close()
        assert extractor.links == [("Software Engineer", "/jobs/1")]

    def test_extracts_absolute_links(self):
        html = '<a href="https://example.com/jobs/2">Designer</a>'
        extractor = _LinkExtractor()
        extractor.feed(html)
        extractor.close()
        assert extractor.links == [("Designer", "https://example.com/jobs/2")]

    def test_ignores_links_without_href(self):
        html = "<a>No link</a>"
        extractor = _LinkExtractor()
        extractor.feed(html)
        extractor.close()
        assert extractor.links == []

    def test_ignores_links_with_empty_text(self):
        html = '<a href="/jobs/1">  </a>'
        extractor = _LinkExtractor()
        extractor.feed(html)
        extractor.close()
        assert extractor.links == []

    def test_handles_incremental_feeding(self):
        extractor = _LinkExtractor()
        extractor.feed('<a href="/jobs/1">Soft')
        extractor.feed("ware Engi")
        extractor.feed("neer</a>")
        extractor.close()
        assert extractor.links == [("Software Engineer", "/jobs/1")]

    def test_multiple_links(self):
        html = """
        <a href="/jobs/1">Engineer</a>
        <a href="/jobs/2">Designer</a>
        <a href="/jobs/3">PM</a>
        """
        extractor = _LinkExtractor()
        extractor.feed(html)
        extractor.close()
        assert len(extractor.links) == 3
        assert extractor.links[0] == ("Engineer", "/jobs/1")
        assert extractor.links[1] == ("Designer", "/jobs/2")
        assert extractor.links[2] == ("PM", "/jobs/3")

    def test_large_html_streaming(self):
        chunks = []
        for i in range(100):
            chunks.append(f'<a href="/jobs/{i}">Job Title {i}</a>\n')
        extractor = _LinkExtractor()
        for chunk in chunks:
            extractor.feed(chunk)
        extractor.close()
        assert len(extractor.links) == 100

    def test_nested_tags_in_link(self):
        html = '<a href="/jobs/1"><span>Software</span> Engineer</a>'
        extractor = _LinkExtractor()
        extractor.feed(html)
        extractor.close()
        assert len(extractor.links) == 1
        assert extractor.links[0][0] == "Software Engineer"


class TestIsLikelyJobLink:
    # --- Job path patterns (whitelist) ---

    def test_job_path_slash_jobs_id(self):
        assert (
            _is_likely_job_link("Senior Engineer", "https://example.com/jobs/12345")
            is True
        )

    def test_job_path_slash_job_id(self):
        assert (
            _is_likely_job_link("Senior Engineer", "https://example.com/job/12345")
            is True
        )

    def test_job_path_positions(self):
        assert (
            _is_likely_job_link("Analyst", "https://example.com/positions/abc") is True
        )

    def test_job_path_openings(self):
        assert (
            _is_likely_job_link("Manager", "https://example.com/openings/senior-mgr")
            is True
        )

    def test_job_path_role(self):
        assert (
            _is_likely_job_link("Director", "https://example.com/role/director-123")
            is True
        )

    def test_job_path_search(self):
        assert (
            _is_likely_job_link("Search", "https://example.com/jobs/search?q=test")
            is True
        )

    def test_job_path_results(self):
        assert (
            _is_likely_job_link("Results", "https://example.com/jobs/results?q=test")
            is True
        )

    def test_careers_subpath(self):
        assert (
            _is_likely_job_link(
                "HR Business Partner", "https://example.com/careers/hrbp-123"
            )
            is True
        )

    # --- ATS domains (whitelist) ---

    def test_ats_domain_greenhouse(self):
        assert (
            _is_likely_job_link(
                "View open roles", "https://job-boards.greenhouse.io/deepmind"
            )
            is True
        )

    def test_ats_domain_lever(self):
        assert _is_likely_job_link("Apply", "https://jobs.lever.co/company/123") is True

    def test_ats_domain_ashby(self):
        assert (
            _is_likely_job_link("Apply", "https://jobs.ashbyhq.com/company/123") is True
        )

    # --- Job text heuristics (whitelist) ---

    def test_senior_title(self):
        assert (
            _is_likely_job_link(
                "Senior People Analytics Manager", "https://example.com/page"
            )
            is True
        )

    def test_director_title(self):
        assert (
            _is_likely_job_link("Director of Engineering", "https://example.com/page")
            is True
        )

    def test_engineer_title(self):
        assert (
            _is_likely_job_link("Software Engineer", "https://example.com/page") is True
        )

    def test_analyst_title(self):
        assert _is_likely_job_link("Data Analyst", "https://example.com/page") is True

    def test_intern_title(self):
        assert _is_likely_job_link("Summer Intern", "https://example.com/page") is True

    def test_apply_text(self):
        assert _is_likely_job_link("Apply", "https://example.com/page") is True

    # --- File extensions (always reject) ---

    def test_pdf_url(self):
        assert (
            _is_likely_job_link("Interview Guide", "https://example.com/interview.pdf")
            is False
        )

    def test_doc_url(self):
        assert (
            _is_likely_job_link("Job description", "https://example.com/job.docx")
            is False
        )

    # --- Unknown paths without job text (default deny) ---

    def test_generic_page_rejected_by_default(self):
        assert (
            _is_likely_job_link("Solutions", "https://example.com/solutions/") is False
        )

    def test_generic_nav_page_rejected(self):
        assert _is_likely_job_link("Developers", "https://example.com/api/") is False

    def test_about_page_rejected(self):
        assert _is_likely_job_link("About Us", "https://example.com/about") is False

    # --- Specific known non-job pages ---

    def test_privacy_policy(self):
        assert (
            _is_likely_job_link("Privacy Policy", "https://example.com/privacy")
            is False
        )

    def test_terms_of_service(self):
        assert (
            _is_likely_job_link(
                "Terms of Service", "https://example.com/terms-of-service"
            )
            is False
        )

    def test_research_page(self):
        assert (
            _is_likely_job_link("Research", "https://deepmind.com/research/projects/")
            is False
        )

    def test_podcast_page(self):
        assert _is_likely_job_link("Podcast", "https://example.com/podcast/") is False

    def test_brand_page(self):
        assert _is_likely_job_link("Brand", "https://example.com/brand/") is False

    def test_charter_page(self):
        assert (
            _is_likely_job_link("Our Charter", "https://example.com/charter/") is False
        )

    def test_policies_page(self):
        assert (
            _is_likely_job_link("Other Policies", "https://example.com/policies/")
            is False
        )

    # --- Short/empty text ---

    def test_short_text_filtered(self):
        assert _is_likely_job_link("Go", "https://example.com/page") is False

    def test_empty_text_filtered(self):
        assert _is_likely_job_link("", "https://example.com/page") is False

    # --- Job path overrides text ---

    def test_job_path_with_generic_text(self):
        assert (
            _is_likely_job_link("Privacy Engineer", "https://example.com/jobs/12345")
            is True
        )

    # --- ATS domain overrides text ---

    def test_ats_domain_with_generic_text(self):
        assert (
            _is_likely_job_link(
                "Privacy Policy", "https://job-boards.greenhouse.io/company"
            )
            is True
        )

    # --- Google careers search passes (job path) ---

    def test_google_careers_search_passes(self):
        assert (
            _is_likely_job_link(
                "Results",
                "https://www.google.com/about/careers/applications/jobs/results?company=DeepMind",
            )
            is True
        )


class TestLinksToPostings:
    def test_converts_links_to_postings(self):
        crawler = CareersPageCrawler()
        links = [("Software Engineer", "/jobs/1")]
        postings = crawler._links_to_postings(links, 5, "https://example.com")
        assert len(postings) == 1
        assert postings[0].title == "Software Engineer"
        assert postings[0].url == "https://example.com/jobs/1"
        assert postings[0].company_id == 5

    def test_resolves_relative_urls(self):
        crawler = CareersPageCrawler()
        links = [("Engineer", "/careers/1")]
        postings = crawler._links_to_postings(links, 1, "https://example.com/careers")
        assert postings[0].url == "https://example.com/careers/1"

    def test_keeps_absolute_urls(self):
        crawler = CareersPageCrawler()
        links = [("Engineer", "https://other.com/job/1")]
        postings = crawler._links_to_postings(links, 1, "https://example.com")
        assert postings[0].url == "https://other.com/job/1"

    def test_skips_anchor_only_links(self):
        crawler = CareersPageCrawler()
        links = [("Skip", "#section")]
        postings = crawler._links_to_postings(links, 1, "https://example.com")
        assert postings == []

    def test_deduplicates_by_source_id(self):
        crawler = CareersPageCrawler()
        links = [
            ("Engineer", "/jobs/1"),
            ("Engineer", "/jobs/1"),
        ]
        postings = crawler._links_to_postings(links, 1, "https://example.com")
        assert len(postings) == 1

    def test_filters_non_job_links(self):
        crawler = CareersPageCrawler()
        links = [
            ("Senior Engineer", "/jobs/1"),
            ("Privacy Policy", "/privacy"),
            ("Research", "/research/projects/"),
            ("Learn more", "/models/gemini/"),
            ("HR Business Partner", "/careers/hrbp-123"),
        ]
        postings = crawler._links_to_postings(links, 1, "https://example.com")
        titles = [p.title for p in postings]
        assert "Senior Engineer" in titles
        assert "HR Business Partner" in titles
        assert "Privacy Policy" not in titles
        assert "Research" not in titles
        assert "Learn more" not in titles

    def test_filters_generic_nav_links(self):
        crawler = CareersPageCrawler()
        links = [
            ("Solutions", "https://example.com/solutions/"),
            ("Developers", "https://example.com/api/"),
            ("Pricing", "https://example.com/pricing"),
            ("Brand", "https://example.com/brand/"),
            ("Podcast", "https://example.com/podcast/"),
        ]
        postings = crawler._links_to_postings(links, 1, "https://example.com")
        assert postings == []

    def test_filters_pdf_links(self):
        crawler = CareersPageCrawler()
        links = [
            (
                "Interview Guide",
                "https://storage.googleapis.com/deepmind/interview.pdf",
            ),
            ("Software Engineer", "https://example.com/jobs/1"),
        ]
        postings = crawler._links_to_postings(links, 1, "https://example.com")
        titles = [p.title for p in postings]
        assert "Software Engineer" in titles
        assert "Interview Guide" not in titles

    def test_allows_job_title_with_generic_url(self):
        crawler = CareersPageCrawler()
        links = [("Senior People Analytics Manager", "https://example.com/page/xyz")]
        postings = crawler._links_to_postings(links, 1, "https://example.com")
        assert len(postings) == 1
        assert postings[0].title == "Senior People Analytics Manager"

    def test_rejects_vague_text_with_generic_url(self):
        crawler = CareersPageCrawler()
        links = [("Explore", "https://example.com/page/xyz")]
        postings = crawler._links_to_postings(links, 1, "https://example.com")
        assert postings == []


class TestDetectAtsFromLinks:
    def test_greenhouse_board(self):
        links = [
            ("View open roles", "https://job-boards.greenhouse.io/deepmind"),
            ("Privacy Policy", "https://deepmind.com/privacy"),
        ]
        result = detect_ats_from_links(links)
        assert result == ("greenhouse", "deepmind")

    def test_lever_board(self):
        links = [
            ("Privacy", "https://example.com/privacy"),
            ("Jobs", "https://jobs.lever.co/huggingface"),
        ]
        result = detect_ats_from_links(links)
        assert result == ("lever", "huggingface")

    def test_ashby_board(self):
        links = [
            ("Apply", "https://jobs.ashbyhq.com/cognition"),
        ]
        result = detect_ats_from_links(links)
        assert result == ("ashby", "cognition")

    def test_no_ats_links(self):
        links = [
            ("Software Engineer", "https://example.com/jobs/1"),
            ("Privacy Policy", "https://example.com/privacy"),
        ]
        result = detect_ats_from_links(links)
        assert result is None

    def test_empty_links(self):
        result = detect_ats_from_links([])
        assert result is None

    def test_greenhouse_boards_subdomain(self):
        links = [
            ("Careers", "https://boards.greenhouse.io/anysphere"),
        ]
        result = detect_ats_from_links(links)
        assert result == ("greenhouse", "anysphere")

    def test_greenhouse_api_subdomain(self):
        links = [
            ("API", "https://boards-api.greenhouse.io/v1/boards/acme"),
        ]
        result = detect_ats_from_links(links)
        assert result == ("greenhouse", "acme")
