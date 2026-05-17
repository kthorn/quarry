from unittest.mock import MagicMock, patch

import pytest

from quarry.models import Company
from quarry.resolve.description import (
    _LLM_REFUSAL,
    _extract_visible_text,
    _sanitize_wikipedia_title,
    fetch_wikipedia_summary,
    generate_company_description,
)


@pytest.fixture(autouse=True)
def _mock_sleep():
    """Avoid real sleeps during tests (semaphore cooldown)."""
    with patch("quarry.resolve.description.time.sleep"):
        yield


def test_sanitize_wikipedia_title():
    assert _sanitize_wikipedia_title("OpenAI Inc.") == "OpenAI"
    assert _sanitize_wikipedia_title("Anthropic PBC") == "Anthropic"
    assert _sanitize_wikipedia_title("Hugging Face") == "Hugging_Face"


def test_extract_visible_text():
    html = """
    <html>
      <head><script>alert(1)</script></head>
      <body>
        <nav>Menu</nav>
        <main><p>Hello world</p></main>
        <footer>Contact</footer>
      </body>
    </html>
    """
    text = _extract_visible_text(html)
    assert "Hello world" in text
    assert "alert(1)" not in text
    assert "Menu" not in text
    assert "Contact" not in text


def test_fetch_wikipedia_summary_hit():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"extract": "OpenAI is an AI lab."}
    with patch("quarry.resolve.description.httpx.get", return_value=mock_response):
        result = fetch_wikipedia_summary("OpenAI")
        assert result == "OpenAI is an AI lab."


def test_fetch_wikipedia_summary_miss():
    import httpx

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404 Not Found", request=MagicMock(), response=MagicMock(status_code=404)
    )
    mock_response.status_code = 404
    with patch("quarry.resolve.description.httpx.get", return_value=mock_response):
        result = fetch_wikipedia_summary("NonExistentCorp123")
        assert result is None


def test_fetch_wikipedia_summary_disambiguation_fallback():
    """Bare name is a disambiguation page, fallback to (company) works."""
    disambig = MagicMock()
    disambig.status_code = 200
    disambig.json.return_value = {
        "type": "disambiguation",
        "extract": "Abbott may refer to:",
    }
    article = MagicMock()
    article.status_code = 200
    article.json.return_value = {
        "extract": "Abbott Laboratories is a medical devices company.",
    }
    with patch(
        "quarry.resolve.description.httpx.get",
        side_effect=[disambig, article],
    ):
        result = fetch_wikipedia_summary("Abbott")
        assert result == "Abbott Laboratories is a medical devices company."


def test_fetch_wikipedia_summary_disambiguation_no_fallback():
    """Bare name is disambiguation, fallback also fails → None."""
    import httpx

    def _make_404():
        m = MagicMock()
        m.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404 Not Found", request=MagicMock(), response=MagicMock(status_code=404)
        )
        return m

    disambig = MagicMock()
    disambig.status_code = 200
    disambig.json.return_value = {
        "type": "disambiguation",
        "extract": "CoreWeave may refer to:",
    }
    # Tenacity retries _fetch_wikipedia_title up to 3 times,
    # so the fallback 404 consumes 3 mock calls.
    misses = [_make_404() for _ in range(3)]
    with patch(
        "quarry.resolve.description.httpx.get",
        side_effect=[disambig, *misses],
    ):
        result = fetch_wikipedia_summary("CoreWeave")
        assert result is None


def test_generate_company_description_wikipedia():
    company = Company(name="OpenAI", domain="openai.com")
    with (
        patch(
            "quarry.resolve.description.fetch_wikipedia_summary",
            return_value="OpenAI is an AI lab.",
        ),
        patch(
            "quarry.resolve.description.fetch_website_text",
        ) as mock_website,
    ):
        with patch(
            "quarry.resolve.description.complete",
            return_value="OpenAI builds large language models.",
        ):
            desc, source = generate_company_description(company)
            assert desc == "OpenAI builds large language models."
            assert source == "wikipedia"
            mock_website.assert_not_called()


def test_generate_company_description_fallback():
    company = Company(name="TinyStartup", domain="tinystartup.io")
    with (
        patch("quarry.resolve.description.fetch_wikipedia_summary", return_value=None),
        patch(
            "quarry.resolve.description.fetch_website_text",
            return_value="We make widgets.",
        ),
        patch(
            "quarry.resolve.description.complete",
            return_value="TinyStartup makes widgets.",
        ),
    ):
        desc, source = generate_company_description(company)
        assert desc == "TinyStartup makes widgets."
        assert source == "website"


def test_generate_company_description_both_fail():
    """When both Wikipedia and website miss, source should be 'pending'."""
    company = Company(name="GhostCorp", domain="ghostcorp.example")
    with (
        patch("quarry.resolve.description.fetch_wikipedia_summary", return_value=None),
        patch("quarry.resolve.description.fetch_website_text", return_value=None),
        patch(
            "quarry.resolve.description.complete",
            return_value="GhostCorp is unknown.",
        ),
    ):
        desc, source = generate_company_description(company)
        assert desc == "GhostCorp is unknown."
        assert source == "pending"


def test_llm_refusal_detection():
    """LLM returns a refusal → use minimal fallback."""
    company = Company(name="ObscureCo", domain="obscure.example")
    with (
        patch("quarry.resolve.description.fetch_wikipedia_summary", return_value=None),
        patch("quarry.resolve.description.fetch_website_text", return_value=None),
        patch(
            "quarry.resolve.description.complete",
            return_value=(
                "I don't have enough information to provide a summary. "
                "Could you provide more details about this company?"
            ),
        ),
    ):
        desc, source = generate_company_description(company)
        assert desc == "ObscureCo is a company."
        assert source == "pending"


def test_llm_refusal_pattern_matches():
    """_LLM_REFUSAL regex catches common refusal phrases."""
    assert _LLM_REFUSAL.search("I don't have enough information to summarize.")
    assert _LLM_REFUSAL.search("I cannot provide a summary of this company.")
    assert _LLM_REFUSAL.search("I'm unable to answer that question.")
    assert _LLM_REFUSAL.search("Could you provide more context?")
    assert _LLM_REFUSAL.search("There is no information available about this.")
    assert _LLM_REFUSAL.search("Not enough context to generate a description.")
    assert _LLM_REFUSAL.search("Unable to provide a meaningful summary.")
    # Good responses should NOT match
    assert not _LLM_REFUSAL.search("OpenAI is an artificial intelligence lab.")
    assert not _LLM_REFUSAL.search("They build large language models.")
