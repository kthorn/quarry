from unittest.mock import MagicMock, patch

from quarry.models import Company
from quarry.resolve.description import (
    _extract_visible_text,
    _sanitize_wikipedia_title,
    fetch_wikipedia_summary,
    generate_company_description,
)


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


def test_generate_company_description_wikipedia():
    company = Company(name="OpenAI", domain="openai.com")
    with (
        patch(
            "quarry.resolve.description.fetch_wikipedia_summary",
            return_value="OpenAI is an AI lab.",
        ),
        patch(
            "quarry.resolve.description.complete",
            return_value="OpenAI builds large language models.",
        ),
    ):
        desc, source = generate_company_description(company)
        assert desc == "OpenAI builds large language models."
        assert source == "wikipedia"


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
