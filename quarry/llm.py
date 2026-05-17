"""LLM client — unified interface for Bedrock and OpenRouter.

This is the first concrete LLM invocation layer in the codebase.
Config lives in quarry/config.py; this module handles the actual calls.
"""

import json
import logging
from typing import Literal

import httpx
from botocore.exceptions import ClientError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from quarry.config import settings

log = logging.getLogger(__name__)

_bedrock_client = None
_openrouter_client = None


class LLMError(Exception):
    """Raised when an LLM call fails after all retries."""

    pass


def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        import boto3

        session = boto3.Session(profile_name=settings.aws_profile)
        _bedrock_client = session.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
        )
    return _bedrock_client


def _get_openrouter_client() -> httpx.Client:
    global _openrouter_client
    if _openrouter_client is None:
        _openrouter_client = httpx.Client(
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "HTTP-Referer": "https://github.com/kthorn/quarry",
                "X-Title": "Quarry",
            },
        )
    return _openrouter_client


def _call_bedrock(prompt: str, model: str | None = None) -> str:
    client = _get_bedrock_client()
    model_id = model or "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "messages": [
            {"role": "user", "content": prompt},
        ],
    }
    response = client.invoke_model(
        modelId=model_id,
        body=json.dumps(body),
    )
    response_body = json.loads(response["body"].read())
    content = response_body.get("content", [])
    if content:
        return content[0].get("text", "").strip()
    return ""


def _call_openrouter(prompt: str, model: str | None = None) -> str:
    client = _get_openrouter_client()
    model_id = model or settings.openrouter_model or "anthropic/claude-3-haiku"
    response = client.post(
        "https://openrouter.ai/api/v1/chat/completions",
        json={
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1024,
        },
    )
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices", [])
    if choices:
        return choices[0]["message"]["content"].strip()
    return ""


@retry(
    retry=retry_if_exception_type((ClientError, httpx.HTTPStatusError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def complete(
    prompt: str,
    model: str | None = None,
    provider: Literal["bedrock", "openrouter"] | None = None,
) -> str:
    """Send a prompt to the configured LLM and return the text response.

    Args:
        prompt: The prompt text to send.
        model: Override the default model for this call.
        provider: Override the configured provider for this call.

    Returns:
        The LLM's text response, stripped of leading/trailing whitespace.

    Raises:
        LLMError: If all retries are exhausted.
    """
    _provider = provider or settings.llm_provider
    try:
        if _provider == "bedrock":
            return _call_bedrock(prompt, model)
        elif _provider == "openrouter":
            return _call_openrouter(prompt, model)
        else:
            raise LLMError(f"Unknown LLM provider: {_provider}")
    except (ClientError, httpx.HTTPStatusError) as e:
        log.error("LLM call failed after retries: %s", e)
        raise LLMError(f"LLM call failed: {e}") from e
