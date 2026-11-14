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


def test_agy_cli_client_large_prompt_uses_stdin_pipe(mocker: MockerFixture) -> None:
    """Tests that large prompts (>4000 chars) are piped via stdin to prevent Win32 overflow.

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
        stdout="Análise detalhada concluída com sucesso.",
        stderr="",
    )

    client = AGYCLIClient()
    large_prompt = "A" * 5000
    result = client.generate_text(
        system_prompt="Sistema",
        user_prompt=large_prompt,
    )

    assert result == "Análise detalhada concluída com sucesso."
    mock_run.assert_called_once()
    call_args, call_kwargs = mock_run.call_args
    cmd = call_args[0]
    assert cmd[0] == "agy"
    # Ensure input was piped via stdin keyword argument
    assert "input" in call_kwargs
    assert len(call_kwargs["input"]) > 5000


def test_agy_cli_client_resilient_json_extraction_with_logs_and_fences(
    mocker: MockerFixture,
) -> None:
    """Tests that generate_structured parses JSON even when surrounded by logs and fences.

    Args:
        mocker: Pytest mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mock_run = mocker.patch("subprocess.run")
    noisy_output = (
        "[INFO] Extension 'auth' initialized successfully.\n"
        "[DEBUG] Model gemini-2.5-pro loaded with 0.2 temperature.\n"
        "```json\n"
        '{\n  "topic": "Estrutura de Capital Avançada",\n  "score": 9.9\n}\n'
        "```\n"
        "[INFO] Execution completed in 1.2s.\n"
    )
    mock_run.return_value = mocker.MagicMock(
        returncode=0,
        stdout=noisy_output,
        stderr="",
    )

    client = AGYCLIClient()
    result = client.generate_structured(
        system_prompt="Instruções",
        user_prompt="Entrada",
        response_model=SampleOutputModel,
    )

    assert result.topic == "Estrutura de Capital Avançada"
    assert result.score == 9.9


def test_agy_cli_client_stream_json_ndjson_parsing(mocker: MockerFixture) -> None:
    """Tests that large prompts parse stream-json NDJSON result events and isolate cwd.

    Args:
        mocker: Pytest mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mock_run = mocker.patch("subprocess.run")
    result_event = {
        "event": "result",
        "result": {
            "status": "SUCCESS",
            "response": json.dumps({"topic": "Redes Neurais", "score": 9.5}),
        },
    }
    ndjson_stdout = (
        '{"event":"init","conversation_id":"abc"}\n'
        '{"event":"step_update","step_update":{"step_index":0}}\n'
        f"{json.dumps(result_event)}\n"
    )
    mock_run.return_value = mocker.MagicMock(
        returncode=0,
        stdout=ndjson_stdout,
        stderr="",
    )

    client = AGYCLIClient()
    result = client.generate_structured(
        system_prompt="Sistema",
        user_prompt="X" * 5000,
        response_model=SampleOutputModel,
    )

    assert result.topic == "Redes Neurais"
    assert result.score == 9.5
    call_args, call_kwargs = mock_run.call_args
    cmd = call_args[0]
    assert "--input-format" in cmd
    assert "stream-json" in cmd
    assert "--disable-slash-commands" in cmd
    assert call_kwargs.get("encoding") == "utf-8"
    assert "cwd" in call_kwargs
    parsed_input = json.loads(call_kwargs["input"].strip())
    assert parsed_input["event"] == "user"
    assert len(parsed_input["message"]["content"]) > 5000


def test_agy_cli_client_stream_json_error_raises(mocker: MockerFixture) -> None:
    """Tests that stream-json result events with status ERROR raise RuntimeError.

    Args:
        mocker: Pytest mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mock_run = mocker.patch("subprocess.run")
    ndjson_stdout = (
        '{"event":"init","conversation_id":"abc"}\n'
        '{"event":"result","result":{"status":"ERROR","response":"","error":"rate limit"}}\n'
    )
    mock_run.return_value = mocker.MagicMock(
        returncode=0,
        stdout=ndjson_stdout,
        stderr="",
    )

    client = AGYCLIClient()
    with pytest.raises(RuntimeError, match="AGY CLI stream-json error: rate limit"):
        client.generate_text(system_prompt="Sys", user_prompt="X" * 5000)


def test_gemini_rest_client_parses_thinking_level(mocker: MockerFixture) -> None:
    """Tests that GeminiRESTClient splits ':thinking_level' and sends thinkingConfig.

    Args:
        mocker: Pytest mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mock_post = mocker.patch("httpx.Client.post")
    mock_resp = mocker.MagicMock()
    mock_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": json.dumps({"topic": "T", "score": 9.0})}]}}]
    }
    mock_post.return_value = mock_resp

    client = GeminiRESTClient(api_key="test-key", model="gemini-4-hydrogen:medium")
    result = client.generate_structured(
        system_prompt="Sys",
        user_prompt="User",
        response_model=SampleOutputModel,
    )

    assert client.model == "gemini-4-hydrogen"
    assert client.thinking_level == "medium"
    assert result.topic == "T"
    call_args, call_kwargs = mock_post.call_args
    assert "/models/gemini-4-hydrogen:generateContent" in call_args[0]
    assert call_kwargs["json"]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "medium"}


def test_gemini_rest_client_retries_on_503_and_succeeds(mocker: MockerFixture) -> None:
    """Tests that GeminiRESTClient retries on 503 Service Unavailable and succeeds.

    Args:
        mocker: Pytest mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    import httpx

    mock_sleep = mocker.patch("time.sleep")
    req = httpx.Request("POST", "https://example.com")
    resp_503 = httpx.Response(503, request=req)
    err_503 = httpx.HTTPStatusError("503", request=req, response=resp_503)

    ok_resp = mocker.MagicMock()
    ok_resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]}

    mock_post = mocker.patch("httpx.Client.post", side_effect=[err_503, ok_resp])

    client = GeminiRESTClient(api_key="test-key", model="gemini-4-hydrogen", max_retries=2)
    result = client.generate_text(system_prompt="Sys", user_prompt="User")

    assert result == "OK"
    assert mock_post.call_count == 2
    mock_sleep.assert_called_once_with(2.0)


def test_gemini_rest_client_raises_after_exhausting_retries(mocker: MockerFixture) -> None:
    """Tests that GeminiRESTClient re-raises HTTPStatusError after max_retries.

    Args:
        mocker: Pytest mock fixture.

    Returns:
        None.

    Raises:
        None.
    """
    import httpx

    mocker.patch("time.sleep")
    req = httpx.Request("POST", "https://example.com")
    resp_503 = httpx.Response(503, request=req)
    err_503 = httpx.HTTPStatusError("503", request=req, response=resp_503)

    mock_post = mocker.patch("httpx.Client.post", side_effect=err_503)

    client = GeminiRESTClient(api_key="test-key", model="gemini-4-hydrogen", max_retries=2)
    with pytest.raises(httpx.HTTPStatusError):
        client.generate_text(system_prompt="Sys", user_prompt="User")

    assert mock_post.call_count == 3


def test_gemini_rest_client_records_usage_metadata(
    mocker: MockerFixture,
    tmp_path: object,
) -> None:
    """Tests that GeminiRESTClient appends usageMetadata to usage_log_path.

    Args:
        mocker: Pytest mock fixture.
        tmp_path: Pytest temporary directory fixture.

    Returns:
        None.

    Raises:
        None.
    """
    from pathlib import Path

    log_file = Path(str(tmp_path)) / "llm_usage.jsonl"
    ok_resp = mocker.MagicMock()
    ok_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "OK"}]}}],
        "usageMetadata": {
            "promptTokenCount": 1200,
            "candidatesTokenCount": 350,
            "thoughtsTokenCount": 150,
            "totalTokenCount": 1700,
        },
    }
    mocker.patch("httpx.Client.post", return_value=ok_resp)

    client = GeminiRESTClient(
        api_key="test-key",
        model="gemini-4-hydrogen:medium",
        usage_log_path=log_file,
    )
    result = client.generate_text(system_prompt="Sys", user_prompt="User")

    assert result == "OK"
    assert log_file.is_file()
    entry = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert entry["model"] == "gemini-4-hydrogen"
    assert entry["thinking_level"] == "medium"
    assert entry["prompt_tokens"] == 1200
    assert entry["candidates_tokens"] == 350
    assert entry["thoughts_tokens"] == 150
    assert entry["total_tokens"] == 1700
