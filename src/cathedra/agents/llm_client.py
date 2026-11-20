"""Structured LLM client protocol and interfaces for pipeline agent nodes.

Defines the dependency injection protocol for interacting with Language Models,
enabling offline deterministic testing without consuming API tokens, alongside
a concrete REST client for production use with Google Gemini.
"""

import json
import os
import re
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, TypeVar, runtime_checkable

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

T = TypeVar("T", bound=BaseModel)


def extract_json_payload(raw_output: str) -> str:
    """Extracts JSON payload from raw LLM or CLI output.

    Handles outer markdown fences, log preambles, and conversational postambles
    by locating the balanced outermost '{...}' or '[...]' envelope.

    Args:
        raw_output: Raw string returned from LLM execution.

    Returns:
        Clean JSON substring ready for model validation.

    Raises:
        None.
    """
    stripped = raw_output.strip()

    # 1. Try stripping outer markdown code fences if wrapped
    if stripped.startswith("```"):
        fenced = re.sub(r"^```(?:json)?\s*", "", stripped)
        fenced = re.sub(r"\s*```$", "", fenced).strip()
        stripped = fenced

    # 2. Check if already clean JSON
    if (stripped.startswith("{") and stripped.endswith("}")) or (
        stripped.startswith("[") and stripped.endswith("]")
    ):
        return stripped

    # 3. Locate outermost balanced '{' and '}'
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return stripped[first_brace : last_brace + 1].strip()

    # 4. Locate outermost balanced '[' and ']'
    first_bracket = stripped.find("[")
    last_bracket = stripped.rfind("]")
    if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
        return stripped[first_bracket : last_bracket + 1].strip()

    return stripped


@runtime_checkable
class StructuredLLMClient(Protocol):
    """Protocol defining structured and raw text generation capabilities for LLMs.

    All pipeline agent nodes rely on this protocol for language model interactions,
    allowing real API clients and deterministic test mocks to be interchanged.
    """

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float = 0.2,
    ) -> T:
        """Generates a validated structured response matching a Pydantic model.

        Args:
            system_prompt: Instructions and behavioral constraints for the model.
            user_prompt: Input payload and context provided for generation.
            response_model: Pydantic model class defining the expected schema.
            temperature: Sampling temperature controlling generation randomness.

        Returns:
            An instantiated and validated instance of the response model type T.

        Raises:
            Exception: If generation or schema validation fails.
        """
        ...

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
    ) -> str:
        """Generates raw text response from the language model.

        Args:
            system_prompt: Instructions and behavioral constraints for the model.
            user_prompt: Input payload and context provided for generation.
            temperature: Sampling temperature controlling generation randomness.

        Returns:
            The raw text string produced by the model.

        Raises:
            Exception: If generation fails.
        """
        ...


class GeminiRESTClient:
    """REST API client for Google Gemini models conforming to StructuredLLMClient protocol.

    Attributes:
        api_key: Google Gemini secret API key.
        model: Target model name.
        timeout: Network timeout in seconds.
    """

    _RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        api_key: str | SecretStr,
        model: str = "gemini-2.5-pro",
        timeout: float = 300.0,
        max_retries: int = 4,
        base_delay: float = 2.0,
        usage_log_path: Path | None = Path("logs/llm_usage.jsonl"),
    ) -> None:
        """Initializes GeminiRESTClient with API credentials and model configuration.

        Args:
            api_key: Google Gemini secret API key.
            model: Model name string.
            timeout: Network timeout in seconds.
            max_retries: Maximum retry attempts on transient HTTP/network errors.
            base_delay: Initial backoff delay in seconds before retrying.
            usage_log_path: Optional JSONL file path to append token usage metadata.

        Returns:
            None.

        Raises:
            ValueError: If api_key is empty.
        """
        secret = api_key if isinstance(api_key, SecretStr) else SecretStr(api_key)
        if not secret.get_secret_value():
            raise ValueError("Gemini API key must not be empty.")
        if secret.get_secret_value() in model:
            raise ValueError("Gemini model identifier contains sensitive data.")
        self.api_key: SecretStr = secret
        base_model, thinking_level = self._parse_model_spec(model)
        self.model: str = base_model
        self.thinking_level: str | None = thinking_level
        self.timeout: float = timeout
        self.max_retries: int = max_retries
        self.base_delay: float = base_delay
        self.usage_log_path: Path | None = usage_log_path

    def _post_with_retry(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Executes a POST request with exponential backoff on transient errors.

        Args:
            url: Target Gemini REST endpoint URL.
            payload: JSON request body.

        Returns:
            Parsed JSON response dictionary.

        Raises:
            RuntimeError: If all retry attempts fail or a non-retryable error occurs.
        """
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(
                        url,
                        json=payload,
                        headers={"x-goog-api-key": self.api_key.get_secret_value()},
                    )
                    resp.raise_for_status()
                    result: dict[str, Any] = resp.json()
                    self._record_usage(result)
                    return result
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status not in self._RETRYABLE_STATUS_CODES or attempt >= self.max_retries:
                    raise RuntimeError(f"Gemini request failed with HTTP {status}.") from None
            except httpx.TimeoutException:
                if attempt >= self.max_retries:
                    raise RuntimeError("Gemini request timed out.") from None
            except httpx.TransportError:
                if attempt >= self.max_retries:
                    raise RuntimeError("Gemini request failed due to a network error.") from None
            except httpx.HTTPError:
                raise RuntimeError("Gemini request failed.") from None
            except json.JSONDecodeError:
                raise ValueError("Gemini returned an invalid JSON response.") from None
            time.sleep(self.base_delay * (2**attempt))

        raise RuntimeError("Unreachable retry loop exit")

    def _record_usage(self, response_data: dict[str, Any]) -> None:
        """Appends token usage metadata from a Gemini response to usage_log_path.

        Args:
            response_data: Parsed JSON response dictionary from Gemini REST API.

        Returns:
            None.

        Raises:
            None.
        """
        if self.usage_log_path is None:
            return
        usage = response_data.get("usageMetadata")
        if not isinstance(usage, dict):
            return
        try:
            entry = {
                "timestamp": datetime.now(UTC).isoformat(),
                "model": self.model,
                "thinking_level": self.thinking_level,
                "prompt_tokens": int(usage.get("promptTokenCount", 0)),
                "candidates_tokens": int(usage.get("candidatesTokenCount", 0)),
                "thoughts_tokens": int(usage.get("thoughtsTokenCount", 0)),
                "total_tokens": int(usage.get("totalTokenCount", 0)),
            }
        except (TypeError, ValueError, OverflowError):
            return
        try:
            self.usage_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.usage_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    @staticmethod
    def _parse_model_spec(model: str) -> tuple[str, str | None]:
        """Splits an optional ':thinking_level' suffix from a model identifier.

        Args:
            model: Model identifier string, optionally suffixed with ':<level>'.

        Returns:
            Tuple of (base_model_id, thinking_level_or_none).

        Raises:
            None.
        """
        if ":" in model:
            base, level = model.rsplit(":", 1)
            if base.strip() and level.strip():
                return base.strip(), level.strip().lower()
        return model.strip(), None

    def _build_generation_config(
        self,
        temperature: float,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Builds generationConfig dictionary with optional thinkingConfig.

        Args:
            temperature: Sampling temperature.
            extra: Optional extra configuration keys.

        Returns:
            Configured generationConfig dictionary.

        Raises:
            None.
        """
        config: dict[str, Any] = {"temperature": temperature}
        if self.thinking_level is not None:
            config["thinkingConfig"] = {"thinkingLevel": self.thinking_level}
        if extra:
            config.update(extra)
        return config

    @staticmethod
    def _inline_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
        """Inlines '$defs' and '$ref' in a JSON schema for Gemini REST API compatibility.

        Args:
            schema: Raw JSON schema dictionary from Pydantic's model_json_schema().

        Returns:
            Schema dictionary with all '$ref' pointers resolved inline and '$defs' removed.

        Raises:
            None.
        """
        defs = schema.get("$defs", {})

        def _resolve(node: Any) -> Any:
            if isinstance(node, dict):
                if "$ref" in node and isinstance(node["$ref"], str):
                    ref_name = node["$ref"].rsplit("/", 1)[-1]
                    if ref_name in defs:
                        return _resolve(dict(defs[ref_name]))
                return {k: _resolve(v) for k, v in node.items() if k != "$defs"}
            if isinstance(node, list):
                return [_resolve(item) for item in node]
            return node

        resolved: dict[str, Any] = _resolve(schema)
        return resolved

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float = 0.2,
    ) -> T:
        """Generates structured output matching response_model using Gemini REST API.

        Args:
            system_prompt: Instructions and behavioral constraints.
            user_prompt: Input payload.
            response_model: Pydantic schema model class.
            temperature: Sampling temperature.

        Returns:
            Validated instance of response_model.

        Raises:
            RuntimeError: If API request fails.
            ValueError: If response parsing fails.
        """
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        )
        schema = self._inline_json_schema(response_model.model_json_schema())
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": self._build_generation_config(
                temperature,
                extra={
                    "response_mime_type": "application/json",
                    "response_schema": schema,
                },
            ),
        }
        data = self._post_with_retry(url, payload)

        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError("No candidates returned by Gemini.")

        parts = candidates[0].get("content", {}).get("parts") or [{}]
        raw_json = parts[0].get("text", "{}")
        if self.api_key.get_secret_value() in raw_json:
            raise ValueError("Gemini response contained sensitive data.")
        clean_json = extract_json_payload(raw_json)
        try:
            return response_model.model_validate_json(clean_json)
        except ValidationError:
            raise ValueError("Gemini returned an invalid structured response.") from None

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
    ) -> str:
        """Generates plain text output using Gemini REST API.

        Args:
            system_prompt: Instructions and behavioral constraints.
            user_prompt: Input payload.
            temperature: Sampling temperature.

        Returns:
            Generated text string.

        Raises:
            RuntimeError: If API request fails.
        """
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        )
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": temperature,
            },
        }
        data = self._post_with_retry(url, payload)

        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError("No candidates returned by Gemini.")

        parts = candidates[0].get("content", {}).get("parts") or [{}]
        text = str(parts[0].get("text", ""))
        if self.api_key.get_secret_value() in text:
            raise ValueError("Gemini response contained sensitive data.")
        return text


class AGYCLIClient:
    """CLI-based client for AGY (Antigravity/Gemini CLI) conforming to StructuredLLMClient.

    Executes prompts locally via subprocess using the installed AGY CLI tool,
    eliminating the requirement for direct external REST API calls.

    Attributes:
        model: Target model identifier.
        executable: Name or filesystem path of the AGY binary.
        timeout: Subprocess timeout in seconds.
    """

    def __init__(
        self,
        model: str = "gemini-2.5-pro",
        executable: str = "agy",
        timeout: float = 300.0,
    ) -> None:
        """Initializes AGYCLIClient with model, executable name, and execution timeout.

        Args:
            model: Model name string.
            executable: AGY binary executable name or path.
            timeout: Maximum subprocess execution timeout in seconds.

        Returns:
            None.

        Raises:
            None.
        """
        self.model: str = model
        self.executable: str = executable
        self.timeout: float = timeout

    def _execute_cli(self, prompt: str) -> str:
        """Executes AGY CLI command in non-interactive print mode with prompt input.

        For large prompts (>4000 characters), passes prompt content via standard input
        to prevent command line argument length limitations (Win32 32KB ceiling).

        Args:
            prompt: Formatted prompt string passed to the CLI.

        Returns:
            Raw standard output string from the executed CLI process.

        Raises:
            RuntimeError: If binary is not found or execution returns a non-zero exit code.
            TimeoutError: If execution exceeds the configured timeout threshold.
        """
        run_kwargs: dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "check": True,
            "timeout": self.timeout,
            "cwd": tempfile.gettempdir(),
        }

        if len(prompt) > 4000:
            cmd = [
                self.executable,
                "--input-format",
                "stream-json",
                "--output-format",
                "stream-json",
                "--model",
                self.model,
                "--disable-slash-commands",
                "-p",
                "",
            ]
            ndjson_payload = json.dumps(
                {
                    "event": "user",
                    "message": {"role": "user", "content": prompt},
                },
                ensure_ascii=False,
            )
            run_kwargs["input"] = f"{ndjson_payload}\n"
        else:
            cmd = [
                self.executable,
                "-p",
                prompt,
                "--model",
                self.model,
                "--disable-slash-commands",
            ]

        try:
            result = subprocess.run(
                cmd,
                **run_kwargs,
            )
            return self._parse_cli_stdout(str(result.stdout))
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"AGY CLI binary not found at '{self.executable}'. "
                "Ensure Antigravity/AGY CLI is installed and available in PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"AGY CLI process timed out after {self.timeout}s.") from exc
        except subprocess.CalledProcessError as exc:
            stderr_msg = exc.stderr.strip() if exc.stderr else ""
            stdout_msg = exc.stdout.strip() if exc.stdout else ""
            error_details = stderr_msg or stdout_msg or "Unknown error"
            raise RuntimeError(
                f"AGY CLI execution failed with code {exc.returncode}: {error_details}"
            ) from exc

    @staticmethod
    def _parse_cli_stdout(raw_stdout: str) -> str:
        """Extracts model response text from plain text or stream-json NDJSON stdout.

        Args:
            raw_stdout: Raw standard output string from the AGY CLI subprocess.

        Returns:
            Extracted and stripped response text.

        Raises:
            RuntimeError: If a stream-json result event reports an ERROR status.
        """
        stripped = raw_stdout.strip()
        if not stripped:
            return ""

        result_text: str | None = None
        for line in stripped.splitlines():
            line_str = line.strip()
            if not line_str.startswith("{"):
                continue
            try:
                event_obj = json.loads(line_str)
            except json.JSONDecodeError:
                continue
            if not isinstance(event_obj, dict) or event_obj.get("event") != "result":
                continue
            result_data = event_obj.get("result")
            if not isinstance(result_data, dict):
                continue
            if result_data.get("status") == "ERROR":
                err_msg = str(result_data.get("error") or "Unknown stream-json error")
                raise RuntimeError(f"AGY CLI stream-json error: {err_msg}")
            response = result_data.get("response")
            if isinstance(response, str):
                result_text = response.strip()

        return result_text if result_text is not None else stripped

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
    ) -> str:
        """Generates plain text output using AGY CLI via subprocess.

        Args:
            system_prompt: Instructions and behavioral constraints.
            user_prompt: Input payload and user context.
            temperature: Sampling temperature (guidance parameter).

        Returns:
            Generated text output from AGY CLI.

        Raises:
            RuntimeError: If subprocess execution fails.
            TimeoutError: If subprocess execution exceeds timeout.
        """
        combined_prompt = f"[SYSTEM INSTRUCTIONS]\n{system_prompt}\n\n[USER CONTEXT]\n{user_prompt}"
        return self._execute_cli(combined_prompt)

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float = 0.2,
    ) -> T:
        """Generates structured output matching response_model using AGY CLI.

        Args:
            system_prompt: Instructions and behavioral constraints.
            user_prompt: Input payload and user context.
            response_model: Pydantic schema model class.
            temperature: Sampling temperature.

        Returns:
            Validated instance of response_model.

        Raises:
            RuntimeError: If subprocess execution fails.
            TimeoutError: If subprocess execution exceeds timeout.
            pydantic.ValidationError: If parsed JSON does not conform to response_model.
            ValueError: If output is not valid JSON.
        """
        schema = response_model.model_json_schema()
        schema_json = json.dumps(schema, indent=2, ensure_ascii=False)

        strict_instructions = (
            f"{system_prompt}\n\n"
            "CRITICAL: You must respond ONLY with a raw, valid JSON object matching this "
            f"JSON Schema:\n{schema_json}\n"
            "Do NOT include markdown fences, comments, or any introductory or concluding text."
        )

        combined_prompt = (
            f"[SYSTEM INSTRUCTIONS]\n{strict_instructions}\n\n[USER CONTEXT]\n{user_prompt}"
        )

        raw_output = self._execute_cli(combined_prompt)
        clean_json = extract_json_payload(raw_output)
        return response_model.model_validate_json(clean_json)


def create_llm_client(
    api_key: str | SecretStr | None = None,
    model: str | None = None,
    backend: str | None = None,
) -> StructuredLLMClient:
    """Factory creating a production StructuredLLMClient implementation.

    Args:
        api_key: Optional Gemini API key. Defaults to GEMINI_API_KEY environment variable.
        model: Optional model identifier. Defaults to gemini-2.5-pro.
        backend: Optional backend provider ('gemini' or 'agy').
            Defaults to LLM_BACKEND env var or 'gemini'.

    Returns:
        Configured StructuredLLMClient instance.

    Raises:
        ValueError: If backend is 'gemini' and no API key is provided or configured,
            or if an unsupported backend is specified.
    """
    selected_backend = (backend or os.environ.get("LLM_BACKEND") or "gemini").lower()

    if selected_backend == "agy":
        return AGYCLIClient(model=model or "gemini-2.5-pro")

    if selected_backend == "gemini":
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key or (isinstance(key, SecretStr) and not key.get_secret_value()):
            raise ValueError(
                "Gemini API key is required. Set GEMINI_API_KEY in environment or .env file."
            )
        return GeminiRESTClient(api_key=key, model=model or "gemini-2.5-pro")

    raise ValueError(
        f"Unsupported LLM backend: '{selected_backend}'. Supported backends are 'gemini' and 'agy'."
    )


__all__ = [
    "AGYCLIClient",
    "GeminiRESTClient",
    "StructuredLLMClient",
    "create_llm_client",
    "extract_json_payload",
]
