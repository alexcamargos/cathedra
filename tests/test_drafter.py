"""Unit tests for the academic drafting and decomposition agent node (drafter.py).

Validates loading system prompts, formatting user context payloads, executing
structured generation via FakeLLMClient, and integrating with LessonPipelineState.
"""

from pathlib import Path

import pytest

from mba_wiki.agents.drafter import (
    draft_node,
    format_drafter_user_prompt,
    generate_draft,
    get_drafter_prompt,
)
from mba_wiki.schemas import (
    AtomicZettel,
    DraftResult,
    LessonPipelineState,
    SlideChunk,
    SyllabusModule,
)
from tests.conftest import FakeLLMClient


def test_get_drafter_prompt_loads_from_markdown() -> None:
    """Tests that the drafter system prompt loads dynamically from its markdown file.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    prompt = get_drafter_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 50
    assert "raw_draft" in prompt
    assert "extracted_zettels" in prompt
    assert "AtomicZettel" in prompt


def test_get_drafter_prompt_missing_file_raises(tmp_path: Path) -> None:
    """Tests that get_drafter_prompt raises FileNotFoundError when the file does not exist.

    Args:
        tmp_path: Pytest temporary directory fixture.

    Returns:
        None.

    Raises:
        None.
    """
    missing_path = tmp_path / "non_existent_drafter_prompt.md"
    with pytest.raises(FileNotFoundError, match="Drafter system prompt file not found"):
        get_drafter_prompt(missing_path)


def test_format_drafter_user_prompt_structure() -> None:
    """Tests that format_drafter_user_prompt produces structured markdown context.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    syllabus = SyllabusModule(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        professor="Dr. Roberto Albuquerque",
        syllabus_summary="Decisões de investimento e financiamento.",
        topics=["VPL", "WACC"],
        bibliography=["Brealey, Myers. Princípios de Finanças Corporativas."],
    )
    slides = [
        SlideChunk(
            slide_number=1,
            title="Valor Presente Líquido",
            raw_text="Critério soberano de avaliação de projetos.",
            latex_equations=["\\text{VPL} = \\sum_{t=1}^n \\frac{FC_t}{(1 + r)^t} - I_0"],
            visual_descriptions=["Linha do tempo de fluxo de caixa."],
        )
    ]

    prompt = format_drafter_user_prompt(
        slides=slides,
        syllabus=syllabus,
        lesson_title="Critérios de Decisão de Investimento",
    )

    assert "Finanças Corporativas" in prompt
    assert "Dr. Roberto Albuquerque" in prompt
    assert "Valor Presente Líquido" in prompt
    assert "\\text{VPL}" in prompt
    assert "Linha do tempo de fluxo de caixa." in prompt


def test_generate_draft_with_fake_llm(fake_llm_client: FakeLLMClient) -> None:
    """Tests executing draft generation using pre-configured FakeLLMClient.

    Args:
        fake_llm_client: Mock LLM client fixture.

    Returns:
        None.

    Raises:
        None.
    """
    syllabus = SyllabusModule(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        professor="Dr. Roberto Albuquerque",
        syllabus_summary="Decisões de investimento e estrutura de capital.",
        topics=["VPL", "TIR", "WACC"],
        bibliography=["Brealey & Myers"],
    )
    slides = [
        SlideChunk(
            slide_number=1,
            title="VPL e TIR",
            raw_text="Métodos quantitativos de avaliação.",
            latex_equations=["\\text{VPL} = \\sum \\dots"],
        )
    ]

    canned_zettel = AtomicZettel(
        slug="valor-presente-liquido",
        title="Valor Presente Líquido (VPL)",
        domain_tags=["financas", "valuation"],
        content_markdown="O VPL representa o valor econômico adicionado por um projeto...",
        related_links=["taxa-interna-retorno", "custo-medio-ponderado-capital"],
    )
    canned_result = DraftResult(
        raw_draft=(
            "O método do [[valor-presente-liquido|VPL]] desconta os fluxos futuros à taxa de custo "
            "de capital da empresa, mensurando o incremento patrimonial decorrente da decisão."
        ),
        extracted_zettels=[canned_zettel],
    )
    fake_llm_client.add_structured_response(canned_result)

    result = generate_draft(
        slides=slides,
        syllabus=syllabus,
        client=fake_llm_client,
        lesson_title="Aula 01: Critérios de Investimento",
    )

    assert isinstance(result, DraftResult)
    assert "[[valor-presente-liquido|VPL]]" in result.raw_draft
    assert len(result.extracted_zettels) == 1
    assert result.extracted_zettels[0].slug == "valor-presente-liquido"

    # Verify client invocation parameters
    assert fake_llm_client.last_call is not None
    assert fake_llm_client.last_call.call_type == "structured"
    assert fake_llm_client.last_call.response_model is DraftResult


def test_draft_node_updates_pipeline_state(fake_llm_client: FakeLLMClient) -> None:
    """Tests that draft_node executes generation and updates LessonPipelineState fields.

    Args:
        fake_llm_client: Mock LLM client fixture.

    Returns:
        None.

    Raises:
        None.
    """
    syllabus = SyllabusModule(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        syllabus_summary="Finanças empresariais.",
        topics=["VPL"],
        bibliography=["Brealey"],
    )
    slides = [
        SlideChunk(
            slide_number=1,
            title="Introdução",
            raw_text="Texto do slide inicial.",
        )
    ]
    state = LessonPipelineState(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        lesson_number=1,
        lesson_title="Fundamentos de Finanças",
        lesson_slug="fundamentos-financas",
        source_slide_filename="aula_01.pdf",
        slides=slides,
        syllabus=syllabus,
    )

    zettel = AtomicZettel(
        slug="custo-de-oportunidade",
        title="Custo de Oportunidade",
        domain_tags=["financas", "economia"],
        content_markdown="Representa o melhor retorno preterido ao escolher um investimento.",
        related_links=[],
    )
    canned_result = DraftResult(
        raw_draft="O [[custo-de-oportunidade|custo de oportunidade]] baliza o desconto de fluxos.",
        extracted_zettels=[zettel],
    )
    fake_llm_client.add_structured_response(canned_result)

    updated_state = draft_node(state=state, client=fake_llm_client)

    assert updated_state.raw_draft == canned_result.raw_draft
    assert len(updated_state.extracted_zettels) == 1
    assert updated_state.extracted_zettels[0].slug == "custo-de-oportunidade"


def test_generate_draft_empty_slides_raises(fake_llm_client: FakeLLMClient) -> None:
    """Tests that attempting to generate a draft with an empty slide list raises ValueError.

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
        topics=["Topico"],
        bibliography=["Livro"],
    )

    with pytest.raises(ValueError, match="Cannot draft lesson with empty slide list"):
        generate_draft(slides=[], syllabus=syllabus, client=fake_llm_client)
