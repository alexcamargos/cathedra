"""Offline tests for credential handling in settings, Gemini and the CLI."""

import logging
import traceback
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from mba_wiki.agents.llm_client import GeminiRESTClient
from mba_wiki.cli import app
from mba_wiki.config import Settings

FAKE_SECRET = "fake-test-secret-never-real"


class ResponseModel(BaseModel):
    score: int


def install_mock_transport(
    mocker: MockerFixture, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    """Install a fake transport without network access."""
    real_client = httpx.Client
    transport = httpx.MockTransport(handler)
    mocker.patch(
        "mba_wiki.agents.llm_client.httpx.Client",
        side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
    )


def test_credentials_are_masked_in_settings_and_client() -> None:
    settings = Settings(_env_file=None, gemini_api_key=FAKE_SECRET)
    client = GeminiRESTClient(api_key=FAKE_SECRET)
    assert FAKE_SECRET not in repr(settings)
    assert FAKE_SECRET not in str(settings)
    assert FAKE_SECRET not in settings.model_dump_json()
    assert FAKE_SECRET not in repr(client.api_key)
    assert FAKE_SECRET not in str(client.api_key)


@pytest.mark.parametrize("structured", [False, True])
def test_gemini_sends_key_in_header_without_putting_it_in_url(
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    structured: bool,
) -> None:
    observed: list[httpx.Request] = []
    caplog.set_level(logging.INFO, logger="httpx")

    def handle(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": '{"score":1}'}]}}]}
        )

    install_mock_transport(mocker, handle)
    client = GeminiRESTClient(api_key=FAKE_SECRET, usage_log_path=None)
    if structured:
        assert client.generate_structured("sys", "user", ResponseModel).score == 1
    else:
        assert client.generate_text("sys", "user") == '{"score":1}'
    assert observed[0].headers["x-goog-api-key"] == FAKE_SECRET
    assert FAKE_SECRET not in str(observed[0].url)
    assert FAKE_SECRET not in observed[0].content.decode()
    assert FAKE_SECRET not in caplog.text


@pytest.mark.parametrize("failure", ["http", "transport", "timeout", "decoding"])
def test_gemini_errors_do_not_expose_credentials_in_tracebacks(
    mocker: MockerFixture,
    failure: str,
) -> None:
    attempts = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if failure == "http":
            return httpx.Response(403, text=FAKE_SECRET)
        if failure == "transport":
            raise httpx.ConnectError(f"failed {FAKE_SECRET}", request=request)
        if failure == "decoding":
            raise httpx.DecodingError(f"failed {FAKE_SECRET}", request=request)
        raise httpx.ReadTimeout(f"timed out {FAKE_SECRET}", request=request)

    install_mock_transport(mocker, handle)
    client = GeminiRESTClient(api_key=FAKE_SECRET, max_retries=2, base_delay=0, usage_log_path=None)
    with pytest.raises(RuntimeError) as caught:
        client.generate_text("sys", "user")
    rendered = "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    assert FAKE_SECRET not in str(caught.value)
    assert FAKE_SECRET not in rendered
    assert attempts == (1 if failure in {"http", "decoding"} else 3)
    if failure == "http":
        assert "403" in str(caught.value)


@pytest.mark.parametrize("response_kind", ["no_candidates", "invalid_json", "invalid_schema"])
def test_bad_model_responses_do_not_echo_credentials(
    mocker: MockerFixture,
    response_kind: str,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if response_kind == "no_candidates":
            return httpx.Response(200, json={"candidates": [], "diagnostic": FAKE_SECRET})
        output = FAKE_SECRET if response_kind == "invalid_json" else json_text
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": output}]}}]}
        )

    json_text = '{"score": "' + FAKE_SECRET + '"}'
    install_mock_transport(mocker, handle)
    client = GeminiRESTClient(api_key=FAKE_SECRET, usage_log_path=None)
    with pytest.raises(ValueError) as caught:
        client.generate_structured("sys", "user", ResponseModel)
    rendered = "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    assert FAKE_SECRET not in str(caught.value)
    assert FAKE_SECRET not in rendered


@pytest.mark.parametrize("structured", [False, True])
def test_model_output_cannot_publish_a_credential(mocker: MockerFixture, structured: bool) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        output = '{"score": 1, "echo": "' + FAKE_SECRET + '"}' if structured else FAKE_SECRET
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": output}]}}]}
        )

    install_mock_transport(mocker, handle)
    client = GeminiRESTClient(api_key=FAKE_SECRET, usage_log_path=None)
    with pytest.raises(ValueError, match="sensitive data"):
        if structured:
            client.generate_structured("sys", "user", ResponseModel)
        else:
            client.generate_text("sys", "user")


def test_retryable_http_status_remains_bounded(mocker: MockerFixture) -> None:
    attempts = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, text=FAKE_SECRET)

    install_mock_transport(mocker, handle)
    client = GeminiRESTClient(api_key=FAKE_SECRET, max_retries=2, base_delay=0, usage_log_path=None)
    with pytest.raises(RuntimeError, match="HTTP 429") as caught:
        client.generate_text("sys", "user")
    assert attempts == 3
    assert FAKE_SECRET not in str(caught.value)


def test_invalid_usage_metadata_does_not_expose_credential(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "usageMetadata": {"promptTokenCount": FAKE_SECRET},
                "candidates": [{"content": {"parts": [{"text": "Resposta válida."}]}}],
            },
        )

    install_mock_transport(mocker, handle)
    usage_log = tmp_path / "usage.jsonl"
    client = GeminiRESTClient(api_key=FAKE_SECRET, usage_log_path=usage_log)
    assert client.generate_text("sys", "user") == "Resposta válida."
    assert not usage_log.exists() or FAKE_SECRET not in usage_log.read_text(encoding="utf-8")


def test_model_identifier_cannot_embed_credential() -> None:
    with pytest.raises(ValueError) as caught:
        GeminiRESTClient(api_key=FAKE_SECRET, model=f"modelo-{FAKE_SECRET}")
    assert FAKE_SECRET not in str(caught.value)


def test_cli_error_does_not_expose_credential(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed {FAKE_SECRET}", request=request)

    install_mock_transport(mocker, handle)
    settings = Settings(_env_file=None, llm_backend="gemini", gemini_api_key=FAKE_SECRET)
    mocker.patch("mba_wiki.cli.get_settings", return_value=settings)
    mocker.patch("mba_wiki.agents.llm_client.time.sleep")
    source = tmp_path / "ementa.txt"
    source.write_text("Ementa fictícia", encoding="utf-8")
    result = CliRunner().invoke(
        app, ["init-syllabus", str(source), "--vault", str(tmp_path / "vault")]
    )
    assert result.exit_code != 0
    assert FAKE_SECRET not in result.output
    assert FAKE_SECRET not in repr(result.exception)
