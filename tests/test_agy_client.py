"""Unit tests for the AGY CLI client implementation.

Validates AGYCLIClient command assembly, subprocess execution, error handling,
markdown fence stripping, and JSON schema validation using pytest-mock.
"""

import json
import subprocess

import pytest
from pydantic import BaseModel, Field, ValidationError
from pytest_mock import MockerFixture

from mba_wiki.agents.llm_client import AGYCLIClient, GeminiRESTClient, create_llm_client


class SampleOutputModel(BaseModel):
    """Sample Pydantic model for validating structured output generation.

    Attributes:
        topic: Topic title string.
        score: Numerical score value.
    """

    topic: str = Field(description="Name of the topic")
    score: float = Field(description="Numeric rating score")


def test_agy_cli_client_generate_text_success(mocker: MockerFixture) -> None:
    """Tests successful raw text generation executing AGY CLI via subprocess.run.

    Args:
        mocker: Pytest mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = mocker.MagicMock(
        returncode=0,
        stdout="Conceito de WACC e custo de capital próprio.\n",
        stderr="",
    )

    client = AGYCLIClient(model="gemini-2.5-pro", executable="agy")
    result = client.generate_text(
        system_prompt="Você é um professor de finanças.",
        user_prompt="Explique o WACC em uma frase.",
        temperature=0.3,
    )

    assert result == "Conceito de WACC e custo de capital próprio."
    mock_run.assert_called_once()
    call_args, call_kwargs = mock_run.call_args
    cmd = call_args[0]
    assert cmd[0] == "agy"
    assert "-p" in cmd or "--print" in cmd
    assert call_kwargs.get("capture_output") is True
    assert call_kwargs.get("text") is True
    assert call_kwargs.get("check") is True


def test_agy_cli_client_generate_structured_success(mocker: MockerFixture) -> None:
    """Tests successful structured output extraction and model validation via AGY CLI.

    Args:
        mocker: Pytest mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mock_run = mocker.patch("subprocess.run")
    valid_payload = {"topic": "Estrutura de Capital", "score": 9.8}
    mock_run.return_value = mocker.MagicMock(
        returncode=0,
        stdout=json.dumps(valid_payload),
        stderr="",
    )

    client = AGYCLIClient()
    result = client.generate_structured(
        system_prompt="Analise o tópico.",
        user_prompt="Gere uma avaliação da disciplina.",
        response_model=SampleOutputModel,
        temperature=0.2,
    )

    assert isinstance(result, SampleOutputModel)
    assert result.topic == "Estrutura de Capital"
    assert result.score == 9.8


def test_agy_cli_client_generate_structured_strips_markdown_fences(
    mocker: MockerFixture,
) -> None:
    """Tests that markdown code fences surrounding JSON output are stripped cleanly.

    Args:
        mocker: Pytest mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mock_run = mocker.patch("subprocess.run")
    fenced_output = '```json\n{"topic": "Finanças", "score": 8.5}\n```'
    mock_run.return_value = mocker.MagicMock(
        returncode=0,
        stdout=fenced_output,
        stderr="",
    )

    client = AGYCLIClient()
    result = client.generate_structured(
        system_prompt="Instruções",
        user_prompt="Entrada",
        response_model=SampleOutputModel,
    )

    assert result.topic == "Finanças"
    assert result.score == 8.5


def test_agy_cli_client_binary_not_found_raises(mocker: MockerFixture) -> None:
    """Tests that FileNotFoundError when running the CLI raises a descriptive RuntimeError.

    Args:
        mocker: Pytest mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mocker.patch(
        "subprocess.run",
        side_effect=FileNotFoundError("No such file or directory: 'agy'"),
    )

    client = AGYCLIClient(executable="agy")
    with pytest.raises(RuntimeError, match="AGY CLI binary not found"):
        client.generate_text(system_prompt="Sys", user_prompt="User")


def test_agy_cli_client_called_process_error_raises(mocker: MockerFixture) -> None:
    """Tests that non-zero exit code raises RuntimeError with stderr output.

    Args:
        mocker: Pytest mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mocker.patch(
        "subprocess.run",
        side_effect=subprocess.CalledProcessError(
            returncode=1,
            cmd=["agy", "-p", "prompt"],
            output="",
            stderr="Error: auth expired or invalid flag",
        ),
    )

    client = AGYCLIClient()
    with pytest.raises(RuntimeError, match="AGY CLI execution failed with code 1"):
        client.generate_text(system_prompt="Sys", user_prompt="User")


def test_agy_cli_client_timeout_raises(mocker: MockerFixture) -> None:
    """Tests that subprocess.TimeoutExpired raises TimeoutError.

    Args:
        mocker: Pytest mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mocker.patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["agy"], timeout=60.0),
    )

    client = AGYCLIClient(timeout=60.0)
    with pytest.raises(TimeoutError, match="timed out after 60.0s"):
        client.generate_text(system_prompt="Sys", user_prompt="User")


def test_agy_cli_client_invalid_json_raises(mocker: MockerFixture) -> None:
    """Tests that invalid JSON response raises ValueError or ValidationError.

    Args:
        mocker: Pytest mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = mocker.MagicMock(
        returncode=0,
        stdout="Este é um texto não estruturado, sem JSON.",
        stderr="",
    )

    client = AGYCLIClient()
    with pytest.raises(ValidationError):
        client.generate_structured(
            system_prompt="Sys",
            user_prompt="User",
            response_model=SampleOutputModel,
        )


def test_create_llm_client_factory_backend_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tests factory resolution for backend selection between gemini and agy.

    Args:
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        None.

    Raises:
        None.
    """
    # Default without key or env raises when backend is gemini
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BACKEND", raising=False)

    # Factory explicit backend="agy"
    client_agy = create_llm_client(backend="agy", model="gemini-2.5-pro")
    assert isinstance(client_agy, AGYCLIClient)
    assert client_agy.model == "gemini-2.5-pro"

    # Factory with env LLM_BACKEND="agy"
    monkeypatch.setenv("LLM_BACKEND", "agy")
    client_env_agy = create_llm_client()
    assert isinstance(client_env_agy, AGYCLIClient)

    # Factory explicit backend="gemini"
    monkeypatch.setenv("GEMINI_API_KEY", "test_key")
    client_gemini = create_llm_client(backend="gemini")
    assert isinstance(client_gemini, GeminiRESTClient)
