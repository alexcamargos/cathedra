"""Unit tests for the stylistic humanizer agent node (humanizer.py).

Validates loading system prompts, verifying prose against deterministic linter rules,
intercepting violations, executing remediation retry loops up to 3 attempts,
and raising HumanizerValidationError upon persistent failures.
"""

from pathlib import Path

import pytest

from mba_wiki.agents.humanizer import (
    HumanizerValidationError,
    format_remediation_feedback,
    get_humanizer_prompt,
    humanize_node,
    humanize_text,
)
from mba_wiki.agents.validators import LinterViolation
from mba_wiki.schemas import (
    AtomicZettel,
    HumanizerResult,
    LessonPipelineState,
    SlideChunk,
    SyllabusModule,
)
from tests.conftest import FakeLLMClient


def test_get_humanizer_prompt_loads_from_markdown() -> None:
    """Tests that the humanizer system prompt loads dynamically from its markdown file.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    prompt = get_humanizer_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 50
    assert "travessão" in prompt
    assert "emojis" in prompt
    assert "LaTeX" in prompt


def test_get_humanizer_prompt_missing_file_raises(tmp_path: Path) -> None:
    """Tests that get_humanizer_prompt raises FileNotFoundError when the file does not exist.

    Args:
        tmp_path: Pytest temporary directory fixture.

    Returns:
        None.

    Raises:
        None.
    """
    missing_path = tmp_path / "non_existent_humanizer_prompt.md"
    with pytest.raises(FileNotFoundError, match="Humanizer system prompt file not found"):
        get_humanizer_prompt(missing_path)


def test_format_remediation_feedback_helper() -> None:
    """Tests that format_remediation_feedback constructs clear corrective feedback.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    violations = [
        LinterViolation(
            rule_id="R1_DASH",
            message="Travessões explicativos são proibidos.",
            line_number=2,
            matched_text="—",
        ),
        LinterViolation(
            rule_id="L4_HISTRIONIC_ADJECTIVE",
            message="Adjetivo histriônico proibido: 'crucial'",
            line_number=4,
            matched_text="crucial",
        ),
    ]
    feedback = format_remediation_feedback(
        violations=violations,
        previous_text="Texto com erros...",
    )

    assert "R1_DASH" in feedback
    assert "L4_HISTRIONIC_ADJECTIVE" in feedback
    assert "Linha 2" in feedback
    assert "Texto com erros..." in feedback


def test_humanize_text_single_attempt_success(fake_llm_client: FakeLLMClient) -> None:
    """Tests that text passing linter on the first attempt succeeds without retries.

    Args:
        fake_llm_client: Mock LLM client fixture.

    Returns:
        None.

    Raises:
        None.
    """
    clean_prose = (
        "O método do Valor Presente Líquido desconta os fluxos futuros à taxa de capital. "
        "A tomada de decisão prioriza projetos com saldo positivo, preservando a liquidez."
    )
    fake_llm_client.add_text_response(clean_prose)

    result = humanize_text(
        text="Rascunho inicial da aula.",
        client=fake_llm_client,
        max_attempts=3,
    )

    assert isinstance(result, HumanizerResult)
    assert result.is_valid is True
    assert result.retry_count == 1
    assert result.humanized_text == clean_prose
    assert len(fake_llm_client.calls) == 1


def test_humanize_text_retries_and_remediates(fake_llm_client: FakeLLMClient) -> None:
    """Tests that an initial response with linter violations triggers corrective retries.

    Args:
        fake_llm_client: Mock LLM client fixture.

    Returns:
        None.

    Raises:
        None.
    """
    # Attempt 1 has an em-dash (R1_DASH) and "crucial" (L4_HISTRIONIC_ADJECTIVE)
    flawed_prose = "O método do VPL é crucial — segundo os pesquisadores mais renomados da área."
    # Attempt 2 remediates the issues completely
    remediated_prose = (
        "O método do VPL orienta as decisões de investimento, conforme os pesquisadores da área."
    )
    fake_llm_client.add_text_response(flawed_prose)
    fake_llm_client.add_text_response(remediated_prose)

    result = humanize_text(
        text="Rascunho de aula.",
        client=fake_llm_client,
        max_attempts=3,
    )

    assert result.is_valid is True
    assert result.retry_count == 2
    assert result.humanized_text == remediated_prose
    assert len(fake_llm_client.calls) == 2

    # Verify that the second call contained corrective feedback about the violations
    retry_prompt = fake_llm_client.calls[1].user_prompt
    assert "R1_DASH" in retry_prompt or "L4_HISTRIONIC_ADJECTIVE" in retry_prompt


def test_humanize_text_exceeds_max_attempts_raises(fake_llm_client: FakeLLMClient) -> None:
    """Tests that persistent linter violations after 3 attempts raise HumanizerValidationError.

    Args:
        fake_llm_client: Mock LLM client fixture.

    Returns:
        None.

    Raises:
        None.
    """
    # Configure 3 responses that all contain prohibited em-dashes
    fake_llm_client.add_text_response("Tentativa 1 com — travessão.")
    fake_llm_client.add_text_response("Tentativa 2 ainda com — travessão.")
    fake_llm_client.add_text_response("Tentativa 3 persistindo com — travessão.")

    with pytest.raises(HumanizerValidationError, match="Humanizer exceeded maximum attempts"):
        humanize_text(
            text="Texto inicial.",
            client=fake_llm_client,
            max_attempts=3,
        )

    assert len(fake_llm_client.calls) == 3


def test_humanize_node_updates_pipeline_state(fake_llm_client: FakeLLMClient) -> None:
    """Tests that humanize_node updates LessonPipelineState with humanized prose.

    Args:
        fake_llm_client: Mock LLM client fixture.

    Returns:
        None.

    Raises:
        None.
    """
    syllabus = SyllabusModule(
        discipline_slug="financas",
        discipline_name="Finanças",
        syllabus_summary="Resumo",
        topics=["VPL"],
        bibliography=["Livro"],
    )
    slides = [SlideChunk(slide_number=1, title="VPL", raw_text="Texto")]
    zettel = AtomicZettel(
        slug="vpl",
        title="VPL",
        domain_tags=["financas"],
        content_markdown="Nota conceitual limpa.",
        related_links=[],
    )
    state = LessonPipelineState(
        discipline_slug="financas",
        discipline_name="Finanças",
        lesson_number=1,
        lesson_title="Critérios de Decisão",
        lesson_slug="criterios-decisao",
        source_slide_filename="aula1.pdf",
        slides=slides,
        syllabus=syllabus,
        audited_markdown="Texto auditado para polimento estilístico.",
        extracted_zettels=[zettel],
    )

    clean_humanized = (
        "O método do VPL analisa fluxos de caixa descontados à taxa de atratividade da firma."
    )
    fake_llm_client.add_text_response(clean_humanized)

    updated_state = humanize_node(state=state, client=fake_llm_client)

    assert updated_state.humanized_markdown == clean_humanized
    assert updated_state.humanizer_retry_count == 1
    assert len(updated_state.extracted_zettels) == 1
