"""Tests for JobSpyClient helpers and metadata extraction."""

from quarry.crawlers.jobspy_client import JobSpyClient


class TestSafeStr:
    def test_nan_returns_default(self):
        assert JobSpyClient._safe_str(float("nan"), "Unknown") == "Unknown"

    def test_none_returns_default(self):
        assert JobSpyClient._safe_str(None, "Unknown") == "Unknown"

    def test_empty_string_returns_default(self):
        assert JobSpyClient._safe_str("", "Unknown") == "Unknown"

    def test_whitespace_only_returns_default(self):
        assert JobSpyClient._safe_str("   ", "Unknown") == "Unknown"

    def test_valid_string_returns_stripped(self):
        assert JobSpyClient._safe_str("  Acme  ", "Unknown") == "Acme"

    def test_pandas_na_returns_default(self):
        import pandas as pd

        assert JobSpyClient._safe_str(pd.NA, "Unknown") == "Unknown"


class TestExtractDomain:
    def test_extracts_clean_domain(self):
        assert (
            JobSpyClient._extract_domain("https://www.amperecomputing.com/careers")
            == "amperecomputing.com"
        )

    def test_strips_www(self):
        assert JobSpyClient._extract_domain("http://www.example.com") == "example.com"

    def test_removeprefix_not_lstrip(self):
        # Ensure we use removeprefix (not lstrip, which strips any combo of w/. chars)
        assert (
            JobSpyClient._extract_domain("https://ww2.example.com") == "ww2.example.com"
        )

    def test_none_returns_none(self):
        assert JobSpyClient._extract_domain(None) is None

    def test_empty_returns_none(self):
        assert JobSpyClient._extract_domain("") is None


class TestDetectAtsFromUrl:
    def test_greenhouse_boards(self):
        assert JobSpyClient._detect_ats_from_url(
            "https://boards.greenhouse.io/openai/jobs/123"
        ) == ("greenhouse", "openai", "boards")

    def test_greenhouse_api(self):
        assert JobSpyClient._detect_ats_from_url(
            "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs"
        ) == ("greenhouse", "anthropic", "boards")

    def test_greenhouse_job_boards(self):
        assert JobSpyClient._detect_ats_from_url(
            "https://job-boards.greenhouse.io/deepmind/123"
        ) == ("greenhouse", "deepmind", "job-boards")

    def test_lever(self):
        assert JobSpyClient._detect_ats_from_url(
            "https://jobs.lever.co/huggingface/abc-123"
        ) == ("lever", "huggingface", None)

    def test_ashby(self):
        assert JobSpyClient._detect_ats_from_url(
            "https://jobs.ashbyhq.com/cognition/123"
        ) == ("ashby", "cognition", None)

    def test_ashby_careers(self):
        assert JobSpyClient._detect_ats_from_url(
            "https://careers.ashbyhq.com/openai/123"
        ) == ("ashby", "openai", None)

    def test_unknown_url(self):
        assert JobSpyClient._detect_ats_from_url("https://example.com/jobs") == (
            None,
            None,
            None,
        )

    def test_none_url(self):
        assert JobSpyClient._detect_ats_from_url(None) == (None, None, None)
