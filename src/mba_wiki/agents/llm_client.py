"""Structured LLM client protocol and interfaces for pipeline agent nodes.

Defines the dependency injection protocol for interacting with Language Models,
enabling offline deterministic testing without consuming API tokens, alongside
a concrete REST client for production use with Google Gemini.
"""

import json
import os
import re
import subprocess
from typing import Any, Protocol, TypeVar, runtime_checkable

import httpx
from pydantic import BaseModel

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

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-pro",
        timeout: float = 60.0,
    ) -> None:
        """Initializes GeminiRESTClient with API credentials and model configuration.

        Args:
            api_key: Google Gemini secret API key.
            model: Model name string.
            timeout: Network timeout in seconds.

        Returns:
            None.

        Raises:
            ValueError: If api_key is empty.
        """
        if not api_key:
            raise ValueError("Gemini API key must not be empty.")
        self.api_key: str = api_key
        self.model: str = model
        self.timeout: float = timeout

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
            httpx.HTTPError: If API request fails.
            pydantic.ValidationError: If response parsing fails.
        """
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        schema = response_model.model_json_schema()
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "response_mime_type": "application/json",
                "response_schema": schema,
            },
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError(f"No candidates returned by Gemini: {data}")

        parts = candidates[0].get("content", {}).get("parts") or [{}]
        raw_json = parts[0].get("text", "{}")
        clean_json = extract_json_payload(raw_json)
        return response_model.model_validate_json(clean_json)

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
            httpx.HTTPError: If API request fails.
        """
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": temperature,
            },
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError(f"No candidates returned by Gemini: {data}")

        parts = candidates[0].get("content", {}).get("parts") or [{}]
        return str(parts[0].get("text", ""))


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
        timeout: float = 120.0,
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
            "check": True,
            "timeout": self.timeout,
        }

        if len(prompt) > 4000:
            cmd = [
                self.executable,
                "-p",
                "-",
                "--model",
                self.model,
            ]
            run_kwargs["input"] = prompt
        else:
            cmd = [
                self.executable,
                "-p",
                prompt,
                "--model",
                self.model,
            ]

        try:
            result = subprocess.run(
                cmd,
                **run_kwargs,
            )
            return str(result.stdout).strip()
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
    api_key: str | None = None,
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
        if not key:
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
