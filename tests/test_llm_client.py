"""Unit tests for the concrete Gemini REST API client and factory function.

Validates GeminiRESTClient initialization, network payload formatting, response parsing,
markdown fence stripping, and create_llm_client factory credential resolution using pytest-mock.
"""

from typing import Any

import pytest
from pydantic import BaseModel
from pytest_mock import MockerFixture

from cathedra.agents.llm_client import GeminiRESTClient, create_llm_client


class SampleOutputModel(BaseModel):
    """Sample Pydantic model for testing structured LLM output generation.

    Attributes:
        topic: Topic title string.
        score: Numerical score value.
    """

    topic: str
    score: float


def test_gemini_rest_client_empty_api_key_raises() -> None:
    """Tests that GeminiRESTClient raises ValueError when initialized with an empty key.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    with pytest.raises(ValueError, match="Gemini API key must not be empty"):
        GeminiRESTClient(api_key="")


def test_create_llm_client_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests that create_llm_client raises ValueError when no API key is provided or set in env.

    Args:
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        None.

    Raises:
        None.
    """
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="Gemini API key is required"):
        create_llm_client(api_key=None)


def test_create_llm_client_from_arg_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests create_llm_client creating client instances from arguments or environment.

    Args:
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        None.

    Raises:
        None.
    """
    # From explicit argument
    client_arg = create_llm_client(api_key="explicit_key", model="gemini-custom")
    assert isinstance(client_arg, GeminiRESTClient)
    assert client_arg.api_key.get_secret_value() == "explicit_key"
    assert client_arg.model == "gemini-custom"

    # From environment variable
    monkeypatch.setenv("GEMINI_API_KEY", "env_key")
    client_env = create_llm_client()
    assert isinstance(client_env, GeminiRESTClient)
    assert client_env.api_key.get_secret_value() == "env_key"
    assert client_env.model == "gemini-2.5-pro"


def test_gemini_rest_client_generate_structured_success(mocker: MockerFixture) -> None:
    """Tests successful structured output generation via Gemini REST API.

    Args:
        mocker: Pytest-mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    client = GeminiRESTClient(api_key="test_key", model="gemini-2.5-pro")

    fake_response_data: dict[str, Any] = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": '{"topic": "Valuation", "score": 9.5}'}],
                }
            }
        ]
    }

    mock_resp = mocker.MagicMock()
    mock_resp.json.return_value = fake_response_data
    mock_resp.raise_for_status.return_value = None

    mock_client_instance = mocker.MagicMock()
    mock_client_instance.post.return_value = mock_resp
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_client_instance.__exit__.return_value = None

    mocker.patch("httpx.Client", return_value=mock_client_instance)

    result = client.generate_structured(
        system_prompt="Extract data",
        user_prompt="Input text",
        response_model=SampleOutputModel,
    )

    assert isinstance(result, SampleOutputModel)
    assert result.topic == "Valuation"
    assert result.score == 9.5


def test_gemini_rest_client_generate_structured_strips_markdown_fences(
    mocker: MockerFixture,
) -> None:
    """Tests that generate_structured strips surrounding markdown code fences from JSON.

    Args:
        mocker: Pytest-mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    client = GeminiRESTClient(api_key="test_key")

    fake_response_data: dict[str, Any] = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": '```json\n{"topic": "Finanças", "score": 8.0}\n```'}],
                }
            }
        ]
    }

    mock_resp = mocker.MagicMock()
    mock_resp.json.return_value = fake_response_data
    mock_resp.raise_for_status.return_value = None

    mock_client_instance = mocker.MagicMock()
    mock_client_instance.post.return_value = mock_resp
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_client_instance.__exit__.return_value = None

    mocker.patch("httpx.Client", return_value=mock_client_instance)

    result = client.generate_structured(
        system_prompt="Extract data",
        user_prompt="Input text",
        response_model=SampleOutputModel,
    )

    assert result.topic == "Finanças"
    assert result.score == 8.0


def test_gemini_rest_client_generate_structured_no_candidates_raises(
    mocker: MockerFixture,
) -> None:
    """Tests that generate_structured raises ValueError when response has no candidates.

    Args:
        mocker: Pytest-mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    client = GeminiRESTClient(api_key="test_key")

    mock_resp = mocker.MagicMock()
    mock_resp.json.return_value = {"candidates": []}
    mock_resp.raise_for_status.return_value = None

    mock_client_instance = mocker.MagicMock()
    mock_client_instance.post.return_value = mock_resp
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_client_instance.__exit__.return_value = None

    mocker.patch("httpx.Client", return_value=mock_client_instance)

    with pytest.raises(ValueError, match="No candidates returned by Gemini"):
        client.generate_structured(
            system_prompt="Sys",
            user_prompt="User",
            response_model=SampleOutputModel,
        )


def test_gemini_rest_client_generate_text_success(mocker: MockerFixture) -> None:
    """Tests successful raw text generation via Gemini REST API.

    Args:
        mocker: Pytest-mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    client = GeminiRESTClient(api_key="test_key")

    fake_response_data: dict[str, Any] = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Texto gerado pelo modelo."}],
                }
            }
        ]
    }

    mock_resp = mocker.MagicMock()
    mock_resp.json.return_value = fake_response_data
    mock_resp.raise_for_status.return_value = None

    mock_client_instance = mocker.MagicMock()
    mock_client_instance.post.return_value = mock_resp
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_client_instance.__exit__.return_value = None

    mocker.patch("httpx.Client", return_value=mock_client_instance)

    text = client.generate_text(system_prompt="Sys", user_prompt="User")
    assert text == "Texto gerado pelo modelo."


def test_gemini_rest_client_generate_text_no_candidates_raises(mocker: MockerFixture) -> None:
    """Tests that generate_text raises ValueError when response has no candidates.

    Args:
        mocker: Pytest-mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    client = GeminiRESTClient(api_key="test_key")

    mock_resp = mocker.MagicMock()
    mock_resp.json.return_value = {"candidates": []}
    mock_resp.raise_for_status.return_value = None

    mock_client_instance = mocker.MagicMock()
    mock_client_instance.post.return_value = mock_resp
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_client_instance.__exit__.return_value = None

    mocker.patch("httpx.Client", return_value=mock_client_instance)

    with pytest.raises(ValueError, match="No candidates returned by Gemini"):
        client.generate_text(system_prompt="Sys", user_prompt="User")
