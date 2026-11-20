"""Pytest global fixtures, test data loaders, and FakeLLMClient implementation.

Provides offline mock clients and static data fixtures for tests without making
external API calls or consuming LLM token budgets.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar, cast

import pytest
from pydantic import BaseModel

from cathedra.agents.llm_client import StructuredLLMClient
from cathedra.schemas import SlideChunk, SyllabusModule

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMCallRecord:
    """Historical invocation record of an LLM client method call.

    Attributes:
        call_type: Method invoked ('structured' or 'text').
        system_prompt: System prompt passed to the client.
        user_prompt: User input context passed to the client.
        response_model: Expected Pydantic model type if structured, otherwise None.
        temperature: Sampling temperature passed to the client call.
    """

    call_type: str
    system_prompt: str
    user_prompt: str
    response_model: type[BaseModel] | None
    temperature: float


class FakeLLMClient:
    """Offline mock implementation of StructuredLLMClient for testing.

    Records all interactions and returns pre-configured canned responses without
    making external network requests or consuming API tokens.
    """

    def __init__(
        self,
        default_text_response: str = "",
        default_structured_response: BaseModel | None = None,
        text_responses: list[str] | None = None,
        structured_responses: list[BaseModel] | None = None,
    ) -> None:
        """Initializes FakeLLMClient with optional default and queued responses.

        Args:
            default_text_response: Fallback text response when queue is empty.
            default_structured_response: Fallback model response when queue is empty.
            text_responses: Sequence of text responses to return in FIFO order.
            structured_responses: Sequence of structured model responses in FIFO order.

        Returns:
            None.

        Raises:
            None.
        """
        self.default_text_response: str = default_text_response
        self.default_structured_response: BaseModel | None = default_structured_response
        self._text_responses: list[str] = list(text_responses or [])
        self._structured_responses: list[BaseModel] = list(structured_responses or [])
        self.calls: list[LLMCallRecord] = []

    def add_text_response(self, response: str) -> None:
        """Appends a canned text response to the back of the queue.

        Args:
            response: Text string to be returned by future generate_text calls.

        Returns:
            None.

        Raises:
            None.
        """
        self._text_responses.append(response)

    def set_text_response(self, response: str) -> None:
        """Clears queue and configures a single text response.

        Args:
            response: Sole text string to be returned by next generate_text call.

        Returns:
            None.

        Raises:
            None.
        """
        self._text_responses = [response]

    def add_structured_response(self, response: BaseModel) -> None:
        """Appends a canned structured model response to the back of the queue.

        Args:
            response: Pydantic model instance to be returned by generate_structured.

        Returns:
            None.

        Raises:
            None.
        """
        self._structured_responses.append(response)

    def set_structured_response(self, response: BaseModel) -> None:
        """Clears queue and configures a single structured model response.

        Args:
            response: Sole model instance to be returned by next generate_structured call.

        Returns:
            None.

        Raises:
            None.
        """
        self._structured_responses = [response]

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float = 0.2,
    ) -> T:
        """Simulates structured generation and records invocation history.

        Args:
            system_prompt: Instructions provided to the simulated model.
            user_prompt: Context and payload provided for generation.
            response_model: Target Pydantic model type.
            temperature: Sampling temperature parameter.

        Returns:
            A pre-configured Pydantic model instance of type T.

        Raises:
            RuntimeError: If no canned response matching response_model is available.
        """
        self.calls.append(
            LLMCallRecord(
                call_type="structured",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=response_model,
                temperature=temperature,
            )
        )

        for i, item in enumerate(self._structured_responses):
            if isinstance(item, response_model):
                return cast(T, self._structured_responses.pop(i))

        if self.default_structured_response is not None and isinstance(
            self.default_structured_response, response_model
        ):
            return self.default_structured_response

        raise RuntimeError(
            f"No canned response configured for {response_model.__name__} in FakeLLMClient."
        )

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
    ) -> str:
        """Simulates text generation and records invocation history.

        Args:
            system_prompt: Instructions provided to the simulated model.
            user_prompt: Context and payload provided for generation.
            temperature: Sampling temperature parameter.

        Returns:
            A canned string response.

        Raises:
            RuntimeError: If queue is empty and no default_text_response is configured.
        """
        self.calls.append(
            LLMCallRecord(
                call_type="text",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=None,
                temperature=temperature,
            )
        )

        if self._text_responses:
            return self._text_responses.pop(0)

        if self.default_text_response:
            return self.default_text_response

        raise RuntimeError("No canned text response configured in FakeLLMClient.")

    @property
    def last_call(self) -> LLMCallRecord | None:
        """Retrieves the most recent recorded invocation, if any.

        Args:
            None.

        Returns:
            The last LLMCallRecord or None if no calls have occurred.

        Raises:
            None.
        """
        return self.calls[-1] if self.calls else None

    def reset(self) -> None:
        """Resets call history and clears all queued responses.

        Args:
            None.

        Returns:
            None.

        Raises:
            None.
        """
        self.calls.clear()
        self._text_responses.clear()
        self._structured_responses.clear()


@pytest.fixture
def fixtures_dir() -> Path:
    """Provides path to the static test fixtures directory.

    Args:
        None.

    Returns:
        Absolute Path pointing to tests/fixtures.

    Raises:
        None.
    """
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_syllabus_path(fixtures_dir: Path) -> Path:
    """Provides path to the sample syllabus text fixture.

    Args:
        fixtures_dir: Path to the fixtures folder.

    Returns:
        Path to tests/fixtures/sample_syllabus.txt.

    Raises:
        None.
    """
    return fixtures_dir / "sample_syllabus.txt"


@pytest.fixture
def sample_syllabus_text(sample_syllabus_path: Path) -> str:
    """Loads and provides the raw text content of the sample syllabus.

    Args:
        sample_syllabus_path: Path to sample_syllabus.txt.

    Returns:
        Content string from sample_syllabus.txt.

    Raises:
        FileNotFoundError: If the fixture file does not exist.
    """
    return sample_syllabus_path.read_text(encoding="utf-8")


@pytest.fixture
def sample_slides_path(fixtures_dir: Path) -> Path:
    """Provides path to the sample slides JSON fixture.

    Args:
        fixtures_dir: Path to the fixtures folder.

    Returns:
        Path to tests/fixtures/sample_slides.json.

    Raises:
        None.
    """
    return fixtures_dir / "sample_slides.json"


@pytest.fixture
def sample_slides_json(sample_slides_path: Path) -> list[dict[str, Any]]:
    """Parses and returns raw slide dictionary data from sample_slides.json.

    Args:
        sample_slides_path: Path to sample_slides.json.

    Returns:
        List of deserialized slide dictionaries.

    Raises:
        FileNotFoundError: If the fixture file does not exist.
        json.JSONDecodeError: If JSON syntax is invalid.
    """
    data: list[dict[str, Any]] = json.loads(sample_slides_path.read_text(encoding="utf-8"))
    return data


@pytest.fixture
def sample_slide_chunks(sample_slides_json: list[dict[str, Any]]) -> list[SlideChunk]:
    """Validates and instantiates SlideChunk schemas from sample slides data.

    Args:
        sample_slides_json: Deserialized slide dictionaries.

    Returns:
        List of validated SlideChunk Pydantic models.

    Raises:
        pydantic.ValidationError: If slide data violates SlideChunk schema.
    """
    return [SlideChunk.model_validate(item) for item in sample_slides_json]


@pytest.fixture
def bad_ai_prose_path(fixtures_dir: Path) -> Path:
    """Provides path to the bad AI prose fixture containing deliberate style violations.

    Args:
        fixtures_dir: Path to the fixtures folder.

    Returns:
        Path to tests/fixtures/bad_ai_prose.md.

    Raises:
        None.
    """
    return fixtures_dir / "bad_ai_prose.md"


@pytest.fixture
def bad_ai_prose_text(bad_ai_prose_path: Path) -> str:
    """Loads and returns text containing deliberate AI prose clichés and infractions.

    Args:
        bad_ai_prose_path: Path to bad_ai_prose.md.

    Returns:
        Content string of bad_ai_prose.md.

    Raises:
        FileNotFoundError: If the fixture file does not exist.
    """
    return bad_ai_prose_path.read_text(encoding="utf-8")


@pytest.fixture
def fake_llm_client() -> FakeLLMClient:
    """Provides a fresh instance of FakeLLMClient for testing.

    Args:
        None.

    Returns:
        An instantiated FakeLLMClient.

    Raises:
        None.
    """
    return FakeLLMClient()


def test_fixtures_load_and_paths(
    fixtures_dir: Path,
    sample_syllabus_path: Path,
    sample_slides_path: Path,
    bad_ai_prose_path: Path,
) -> None:
    """Tests that fixture directory and files exist on disk.

    Args:
        fixtures_dir: Fixture directory path.
        sample_syllabus_path: Syllabus text file path.
        sample_slides_path: Slides JSON file path.
        bad_ai_prose_path: Bad AI prose Markdown file path.

    Returns:
        None.

    Raises:
        None.
    """
    assert fixtures_dir.is_dir()
    assert sample_syllabus_path.is_file()
    assert sample_slides_path.is_file()
    assert bad_ai_prose_path.is_file()


def test_sample_syllabus_content(sample_syllabus_text: str) -> None:
    """Tests that sample syllabus fixture contains required academic sections.

    Args:
        sample_syllabus_text: Text content of sample_syllabus.txt.

    Returns:
        None.

    Raises:
        None.
    """
    assert "Finanças Corporativas e Análise de Valor" in sample_syllabus_text
    assert "financas-corporativas" in sample_syllabus_text
    assert "EMENTA E OBJETIVOS" in sample_syllabus_text
    assert "CONTEÚDO PROGRAMÁTICO" in sample_syllabus_text
    assert "BIBLIOGRAFIA BÁSICA" in sample_syllabus_text


def test_sample_slides_valid_chunks(sample_slide_chunks: list[SlideChunk]) -> None:
    """Tests that sample slides successfully parse into SlideChunk models with LaTeX.

    Args:
        sample_slide_chunks: List of validated SlideChunk instances.

    Returns:
        None.

    Raises:
        None.
    """
    assert len(sample_slide_chunks) >= 3
    slide_numbers = [chunk.slide_number for chunk in sample_slide_chunks]
    assert slide_numbers == [1, 2, 3, 4]

    # Verify LaTeX extraction is present
    latex_slides = [chunk for chunk in sample_slide_chunks if chunk.latex_equations]
    assert len(latex_slides) >= 2
    assert any("\\text{VPL}" in eq for chunk in latex_slides for eq in chunk.latex_equations)
    assert any("\\text{WACC}" in eq for chunk in latex_slides for eq in chunk.latex_equations)


def test_bad_ai_prose_violations(bad_ai_prose_text: str) -> None:
    """Tests that bad AI prose fixture contains intentional stylistic violations.

    Args:
        bad_ai_prose_text: Text content from bad_ai_prose.md.

    Returns:
        None.

    Raises:
        None.
    """
    # Prohibited dashes (R1)
    assert "—" in bad_ai_prose_text or "–" in bad_ai_prose_text

    # Emojis and decorative arrows (R2)
    assert "🚀" in bad_ai_prose_text
    assert "→" in bad_ai_prose_text

    # Prohibited mechanical bullet list (R4)
    assert "- **Valor Presente Líquido:**" in bad_ai_prose_text

    # Blacklisted vocabulary (L1 - L7)
    lower_prose = bad_ai_prose_text.lower()
    assert "no cenário atual" in lower_prose
    assert "no seu cerne" in lower_prose
    assert "faca de dois gumes" in lower_prose
    assert "crucial" in lower_prose
    assert "ademais" in lower_prose
    assert "em suma" in lower_prose
    assert "como uma ia" in lower_prose


def test_fake_llm_client_protocol_satisfaction(fake_llm_client: FakeLLMClient) -> None:
    """Tests that FakeLLMClient conforms to StructuredLLMClient protocol at runtime.

    Args:
        fake_llm_client: The mock LLM client instance.

    Returns:
        None.

    Raises:
        None.
    """
    assert isinstance(fake_llm_client, StructuredLLMClient)


def test_fake_llm_client_text_generation(fake_llm_client: FakeLLMClient) -> None:
    """Tests queued and default text generation in FakeLLMClient.

    Args:
        fake_llm_client: The mock LLM client instance.

    Returns:
        None.

    Raises:
        None.
    """
    fake_llm_client.add_text_response("First response")
    fake_llm_client.add_text_response("Second response")

    res1 = fake_llm_client.generate_text("Sys prompt", "User prompt 1", temperature=0.1)
    assert res1 == "First response"
    assert fake_llm_client.last_call is not None
    assert fake_llm_client.last_call.call_type == "text"
    assert fake_llm_client.last_call.user_prompt == "User prompt 1"
    assert fake_llm_client.last_call.temperature == 0.1

    res2 = fake_llm_client.generate_text("Sys prompt", "User prompt 2")
    assert res2 == "Second response"

    # Fallback to default text response
    fake_llm_client.default_text_response = "Fallback text"
    res3 = fake_llm_client.generate_text("Sys prompt", "User prompt 3")
    assert res3 == "Fallback text"


def test_fake_llm_client_structured_generation(fake_llm_client: FakeLLMClient) -> None:
    """Tests queued and default structured Pydantic model generation in FakeLLMClient.

    Args:
        fake_llm_client: The mock LLM client instance.

    Returns:
        None.

    Raises:
        None.
    """
    canned_module = SyllabusModule(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        syllabus_summary="Resumo de finanças",
        topics=["VPL", "WACC"],
        bibliography=["Brealey & Myers"],
    )
    fake_llm_client.add_structured_response(canned_module)

    generated = fake_llm_client.generate_structured(
        system_prompt="Extract syllabus",
        user_prompt="Raw text",
        response_model=SyllabusModule,
        temperature=0.2,
    )
    assert generated == canned_module
    assert fake_llm_client.last_call is not None
    assert fake_llm_client.last_call.call_type == "structured"
    assert fake_llm_client.last_call.response_model is SyllabusModule


def test_fake_llm_client_missing_response_raises(fake_llm_client: FakeLLMClient) -> None:
    """Tests that FakeLLMClient raises RuntimeError when no canned response is configured.

    Args:
        fake_llm_client: The mock LLM client instance.

    Returns:
        None.

    Raises:
        None.
    """
    with pytest.raises(RuntimeError, match="No canned text response"):
        fake_llm_client.generate_text("System", "User")

    with pytest.raises(RuntimeError, match="No canned response configured for SyllabusModule"):
        fake_llm_client.generate_structured("System", "User", response_model=SyllabusModule)


def test_fake_llm_client_call_recording_and_reset(fake_llm_client: FakeLLMClient) -> None:
    """Tests invocation history tracking and reset functionality in FakeLLMClient.

    Args:
        fake_llm_client: The mock LLM client instance.

    Returns:
        None.

    Raises:
        None.
    """
    fake_llm_client.default_text_response = "Ping"
    fake_llm_client.generate_text("Sys 1", "User 1")
    fake_llm_client.generate_text("Sys 2", "User 2")

    assert len(fake_llm_client.calls) == 2
    assert fake_llm_client.calls[0].user_prompt == "User 1"
    assert fake_llm_client.calls[1].user_prompt == "User 2"

    fake_llm_client.reset()
    assert len(fake_llm_client.calls) == 0
    assert fake_llm_client.last_call is None
