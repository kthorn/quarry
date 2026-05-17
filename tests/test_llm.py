import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from quarry.llm import LLMError, complete


def test_complete_bedrock_success():
    with patch("quarry.llm._bedrock_client") as mock_client:
        mock_client.invoke_model.return_value = {
            "body": MagicMock(
                read=lambda: json.dumps(
                    {"content": [{"text": " Hello world "}]}
                ).encode()
            )
        }
        result = complete("Say hello", provider="bedrock")
        assert result == "Hello world"


def test_complete_openrouter_success():
    with patch("quarry.llm._openrouter_client") as mock_client:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": " Hello world "}}]
        }
        mock_client.post.return_value = mock_response
        result = complete("Say hello", provider="openrouter")
        assert result == "Hello world"


def test_complete_retries_on_error():
    with patch("quarry.llm._bedrock_client") as mock_client:
        mock_client.invoke_model.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "throttled"}},
            "InvokeModel",
        )
        with pytest.raises(LLMError):
            complete("Say hello", provider="bedrock")
