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


def test_humanize_text_strips_markdown_fences_and_catches_violations(
    fake_llm_client: FakeLLMClient,
) -> None:
    """Tests that outer markdown fences are stripped and violations inside them are intercepted.

    Args:
        fake_llm_client: Mock LLM client fixture.

    Returns:
        None.

    Raises:
        None.
    """
    # Attempt 1: Wrapped in markdown fence but contains an em-dash (must not bypass linter)
    fenced_with_violation = (
        "```markdown\nO método do VPL analisa decisões — segundo a literatura financeira.\n```"
    )
    # Attempt 2: Clean prose still wrapped in markdown fence
    fenced_clean = (
        "```markdown\nO método do VPL analisa decisões, segundo a literatura financeira.\n```"
    )
    fake_llm_client.add_text_response(fenced_with_violation)
    fake_llm_client.add_text_response(fenced_clean)

    result = humanize_text(
        text="Rascunho de aula.",
        client=fake_llm_client,
        max_attempts=3,
    )

    assert result.is_valid is True
    assert result.retry_count == 2
    # Verify fences were stripped from the final text
    assert not result.humanized_text.startswith("```")
    assert not result.humanized_text.endswith("```")
    assert (
        "O método do VPL analisa decisões, segundo a literatura financeira."
        in result.humanized_text
    )


def test_humanize_node_humanizes_extracted_zettels(fake_llm_client: FakeLLMClient) -> None:
    """Tests that humanize_node processes and polishes content_markdown of extracted zettels.

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
        content_markdown="Rascunho de zettel com termo crucial para avaliação.",
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
        audited_markdown="Texto de aula aprovado na auditoria.",
        extracted_zettels=[zettel],
    )

    clean_lesson = "Texto de aula polido e humanizado com clareza conceitual."
    clean_zettel = "Conceito de VPL estruturado sem adjetivos histriônicos."

    # First call is for the lesson body, second call is for the zettel
    fake_llm_client.add_text_response(clean_lesson)
    fake_llm_client.add_text_response(clean_zettel)

    updated_state = humanize_node(state=state, client=fake_llm_client)

    assert updated_state.humanized_markdown == clean_lesson
    assert len(updated_state.extracted_zettels) == 1
    assert updated_state.extracted_zettels[0].content_markdown == clean_zettel
    assert len(fake_llm_client.calls) == 2


def test_strip_markdown_fences_preserves_internal_code_blocks() -> None:
    """Tests that strip_markdown_fences preserves internal code blocks ending the text.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    from mba_wiki.agents.humanizer import strip_markdown_fences

    wrapped_with_code_at_end = (
        "```markdown\n"
        "# Aula de Modelagem\n\n"
        "Exemplo de cálculo do WACC:\n\n"
        "```python\n"
        "def wacc(e, d, ke, kd, t):\n"
        "    return (e / (e + d)) * ke + (d / (e + d)) * kd * (1 - t)\n"
        "```\n"
        "```"
    )

    stripped = strip_markdown_fences(wrapped_with_code_at_end)
    # The outer wrapper is stripped, but the internal python block is fully preserved!
    assert stripped.startswith("# Aula de Modelagem")
    assert stripped.endswith("```")
    assert "```python" in stripped


def test_humanize_node_pre_sanitizes_simple_violations_without_extra_llm_call(
    fake_llm_client: FakeLLMClient,
) -> None:
    """Tests that deterministic dash violations in zettels are resolved without extra LLM calls.

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
    # Only contains an explanatory dash, which is deterministically resolvable
    zettel = AtomicZettel(
        slug="vpl-mecanico",
        title="VPL Mecânico",
        domain_tags=["financas"],
        content_markdown="O método do VPL — uma métrica objetiva — desconta fluxos futuros.",
        related_links=[],
    )
    state = LessonPipelineState(
        discipline_slug="financas",
        discipline_name="Finanças",
        lesson_number=1,
        lesson_title="Critérios",
        lesson_slug="criterios",
        source_slide_filename="aula1.pdf",
        slides=slides,
        syllabus=syllabus,
        audited_markdown="Texto de aula aprovado na auditoria.",
        extracted_zettels=[zettel],
    )

    clean_lesson = "Texto de aula polido e humanizado com rigor técnico."
    fake_llm_client.add_text_response(clean_lesson)

    updated_state = humanize_node(state=state, client=fake_llm_client)

    # Only 1 LLM call was needed (for the lesson), 0 LLM calls for the zettel!
    assert len(fake_llm_client.calls) == 1
    assert "—" not in updated_state.extracted_zettels[0].content_markdown
    assert "uma métrica objetiva" in updated_state.extracted_zettels[0].content_markdown
