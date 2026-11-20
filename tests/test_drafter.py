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
    StructuredSyllabus,
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
    assert "Bibliografia Recomendada" not in prompt
    assert "Brealey, Myers" not in prompt


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


def test_draft_node_propagates_cross_links_and_tensions(fake_llm_client: FakeLLMClient) -> None:
    """Tests that draft_node populates cross_links and detected_tensions on LessonPipelineState.

    Args:
        fake_llm_client: Mock LLM client fixture.

    Returns:
        None.

    Raises:
        None.
    """
    from mba_wiki.schemas import CrossDisciplineLink, DialecticalTension

    syllabus = SyllabusModule(
        discipline_slug="operacoes",
        discipline_name="Gestão de Operações",
        syllabus_summary="Resumo de operações.",
        topics=["JIT"],
        bibliography=["Livro"],
    )
    slides = [SlideChunk(slide_number=1, title="JIT", raw_text="Just-in-Time.")]
    state = LessonPipelineState(
        discipline_slug="operacoes",
        discipline_name="Gestão de Operações",
        lesson_number=1,
        lesson_title="Just-in-Time",
        lesson_slug="jit",
        source_slide_filename="aula_jit.pdf",
        slides=slides,
        syllabus=syllabus,
    )

    link = CrossDisciplineLink(
        target_discipline_slug="financas",
        target_topic="Necessidade de Capital de Giro",
        connection_type="impact",
        description="JIT reduz estoques e minimiza a necessidade de capital de giro.",
    )
    tension = DialecticalTension(
        slug="eficiencia-vs-resiliencia",
        title="Eficiência vs Resiliência",
        pole_a_discipline="operacoes",
        pole_a_framework="JIT",
        pole_a_thesis="Estoque zero.",
        pole_b_discipline="estrategia",
        pole_b_framework="Resiliência",
        pole_b_thesis="Estoque de segurança.",
        tension_nature="Curto vs Longo prazo",
        synthesis_guidelines="Dual sourcing.",
    )

    draft_result = DraftResult(
        raw_draft="Rascunho de operações com pontes e tensões.",
        cross_links=[link],
        detected_tensions=[tension],
    )
    fake_llm_client.add_structured_response(draft_result)

    updated_state = draft_node(state=state, client=fake_llm_client)

    assert len(updated_state.cross_links) == 1
    assert updated_state.cross_links[0].target_discipline_slug == "financas"
    assert len(updated_state.detected_tensions) == 1
    assert updated_state.detected_tensions[0].slug == "eficiencia-vs-resiliencia"


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


def test_format_drafter_user_prompt_with_full_syllabus() -> None:
    """Tests that format_drafter_user_prompt includes the MBA curriculum summary.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    current_module = SyllabusModule(
        discipline_slug="gestao-estrategica",
        discipline_name="Gestão Estratégica",
        syllabus_summary="Vantagem competitiva e posicionamento.",
        topics=["Cinco Forças", "Recursos e Capacidades"],
        bibliography=["Porter, M. Vantagem Competitiva."],
    )
    other_module = SyllabusModule(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        syllabus_summary="Decisões de investimento e retorno.",
        topics=["VPL", "WACC", "Estrutura de Capital"],
        bibliography=["Brealey, R."],
    )
    full_syllabus = StructuredSyllabus(modules=[current_module, other_module])
    slides = [
        SlideChunk(
            slide_number=1,
            title="Diferenciação e Custo",
            raw_text="Estratégias genéricas de Michael Porter.",
        )
    ]

    prompt = format_drafter_user_prompt(
        slides=slides,
        syllabus=current_module,
        full_syllabus=full_syllabus,
        lesson_title="Estratégias Competitivas",
    )

    assert "## Visão Global do Currículo do MBA" in prompt
    assert "Finanças Corporativas" in prompt
    assert "VPL" in prompt
    assert "WACC" in prompt
    # Current module shouldn't duplicate in the external list or should be clearly delineated
    assert "gestao-estrategica" in prompt


def test_generate_draft_with_full_syllabus_and_tensions(fake_llm_client: FakeLLMClient) -> None:
    """Tests that generate_draft properly injects full_syllabus into the LLM prompt.

    Args:
        fake_llm_client: Mock LLM client fixture.

    Returns:
        None.

    Raises:
        None.
    """
    from mba_wiki.schemas import CrossDisciplineLink, DialecticalTension

    current_module = SyllabusModule(
        discipline_slug="marketing-estrategico",
        discipline_name="Marketing Estratégico",
        syllabus_summary="Estratégia de precificação e segmentação.",
        topics=["Precificação Baseada em Valor", "CAC e LTV"],
        bibliography=["Kotler, P."],
    )
    finance_module = SyllabusModule(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        syllabus_summary="Finanças corporativas.",
        topics=["Margem de Contribuição", "Ponto de Equilíbrio"],
        bibliography=["Brealey, R."],
    )
    full_syllabus = StructuredSyllabus(modules=[current_module, finance_module])
    slides = [
        SlideChunk(
            slide_number=1,
            title="Precificação por Penetração",
            raw_text="Preço reduzido para ganho de escala inicial.",
        )
    ]

    cross_link = CrossDisciplineLink(
        target_discipline_slug="financas-corporativas",
        target_topic="Margem de Contribuição",
        connection_type="impact",
        description="Penetração afeta temporariamente a margem de contribuição unitária.",
    )
    tension = DialecticalTension(
        slug="escala-vs-rentabilidade-imediata",
        title="Escala de Mercado vs Rentabilidade Imediata",
        pole_a_discipline="marketing-estrategico",
        pole_a_framework="Preço de Penetração",
        pole_a_thesis="Maximizar base de clientes.",
        pole_b_discipline="financas-corporativas",
        pole_b_framework="Margem de Contribuição",
        pole_b_thesis="Preservar margem operacional.",
        tension_nature="Curto vs Longo Prazo",
        synthesis_guidelines="Definir teto de subsídio por coorte.",
    )

    expected_result = DraftResult(
        raw_draft="O modelo de precificação por penetração gera tração rápida...",
        cross_links=[cross_link],
        detected_tensions=[tension],
    )
    fake_llm_client.add_structured_response(expected_result)

    result = generate_draft(
        slides=slides,
        syllabus=current_module,
        full_syllabus=full_syllabus,
        client=fake_llm_client,
        lesson_title="Estratégias de Pricing",
    )

    assert len(result.cross_links) == 1
    assert result.cross_links[0].target_discipline_slug == "financas-corporativas"
    assert len(result.detected_tensions) == 1
    assert result.detected_tensions[0].slug == "escala-vs-rentabilidade-imediata"

    assert fake_llm_client.last_call is not None
    assert "Visão Global do Currículo do MBA" in fake_llm_client.last_call.user_prompt


def test_format_drafter_user_prompt_with_transcript() -> None:
    """Tests that format_drafter_user_prompt includes speech transcript when provided.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    from datetime import UTC, datetime

    from mba_wiki.schemas import VideoTranscript

    syllabus = SyllabusModule(
        discipline_slug="gestao",
        discipline_name="Gestão",
        syllabus_summary="Resumo de gestão.",
        topics=["Liderança"],
        bibliography=["Drucker"],
    )
    slides = [SlideChunk(slide_number=1, title="Liderança", raw_text="Liderança servidora.")]
    transcript = VideoTranscript(
        source_filename="aula_lideranca.mp4",
        discipline_slug="gestao",
        duration_seconds=3600.0,
        model_name="large-v3",
        compute_type="int8_float16",
        processed_at=datetime.now(UTC),
        full_text_raw="O professor explicou que liderança servidora é...",
        full_text_cleaned="O professor explicou que liderança servidora é um modelo prático.",
        segments=[],
    )

    prompt = format_drafter_user_prompt(
        slides=slides,
        syllabus=syllabus,
        transcript=transcript,
    )
    assert "Transcrição da Fala do Professor" in prompt
    assert "O professor explicou que liderança servidora é um modelo prático." in prompt


def test_draft_node_transmits_state_transcript(fake_llm_client: FakeLLMClient) -> None:
    """Tests that draft_node transmits state.transcript to LLM user prompt when present.

    Args:
        fake_llm_client: Mock LLM client fixture.

    Returns:
        None.

    Raises:
        None.
    """
    from datetime import UTC, datetime

    from mba_wiki.schemas import VideoTranscript

    syllabus = SyllabusModule(
        discipline_slug="gestao",
        discipline_name="Gestão",
        syllabus_summary="Resumo de gestão.",
        topics=["Liderança"],
        bibliography=["Drucker"],
    )
    slides = [SlideChunk(slide_number=1, title="Liderança", raw_text="Liderança servidora.")]
    transcript = VideoTranscript(
        source_filename="aula_lideranca.mp4",
        discipline_slug="gestao",
        duration_seconds=3600.0,
        model_name="large-v3",
        compute_type="int8_float16",
        processed_at=datetime.now(UTC),
        full_text_raw="Texto bruto",
        full_text_cleaned="Exemplo real de mercado dado pelo professor.",
        segments=[],
    )
    state = LessonPipelineState(
        discipline_slug="gestao",
        discipline_name="Gestão",
        lesson_number=1,
        lesson_title="Liderança",
        lesson_slug="lideranca",
        source_slide_filename="slides.pdf",
        slides=slides,
        syllabus=syllabus,
        transcript=transcript,
    )

    draft_result = DraftResult(raw_draft="Rascunho de liderança.")
    fake_llm_client.add_structured_response(draft_result)

    draft_node(state=state, client=fake_llm_client)

    assert fake_llm_client.last_call is not None
    assert "Transcrição da Fala do Professor" in fake_llm_client.last_call.user_prompt
    assert "Exemplo real de mercado dado pelo professor." in fake_llm_client.last_call.user_prompt
