"""Unit tests for the complete lesson pipeline orchestrator (graph.py).

Validates pipeline state transitions connecting ingestion, drafting, fact-checking,
and stylistic humanizing stages into a typed LessonPipelineState returning WikiLessonOutput.
"""

from datetime import date
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from cathedra.agents.graph import (
    create_initial_state,
    execute_pipeline,
    find_syllabus_module,
    ingestion_node,
    run_lesson_pipeline,
    slugify,
)
from cathedra.agents.humanizer import HumanizerValidationError
from cathedra.schemas import (
    AtomicZettel,
    AuditClaimsResponse,
    ClaimAuditItem,
    DraftResult,
    GuardrailIssue,
    GuardrailResponse,
    LessonPipelineState,
    SlideChunk,
    StructuredSyllabus,
    SyllabusModule,
    WikiLessonOutput,
)
from tests.conftest import FakeLLMClient


@pytest.fixture
def sample_syllabus_module() -> SyllabusModule:
    """Fixture providing a standard SyllabusModule instance for pipeline testing.

    Args:
        None.

    Returns:
        A populated SyllabusModule instance.

    Raises:
        None.
    """
    return SyllabusModule(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        professor="Prof. Dr. Roberto Albuquerque",
        syllabus_summary="Decisões de investimento e financiamento corporativo.",
        topics=["Critérios de Decisão de Investimento", "VPL", "TIR", "Payback"],
        bibliography=["Brealey, Myers & Allen. Princípios de Finanças Corporativas."],
    )


@pytest.fixture
def synthetic_graph_pdf_path(tmp_path: Path) -> Path:
    """Creates a minimal synthetic PDF file with 2 slides for ingestion testing.

    Args:
        tmp_path: Pytest temporary directory fixture.

    Returns:
        Path to the generated PDF file.

    Raises:
        None.
    """
    pdf_path = tmp_path / "slides_aula_01.pdf"
    doc: Any = pymupdf.open()  # type: ignore[no-untyped-call]

    page1 = doc.new_page(width=720, height=405)
    page1.insert_text(
        (50, 60),
        "# Finanças Corporativas: Aula 01\n"
        "Critérios de Decisão de Investimento e Criação de Valor.\n"
        "Prof. Roberto Albuquerque",
        fontsize=16,
    )

    page2 = doc.new_page(width=720, height=405)
    page2.insert_text(
        (50, 60),
        "# Método do VPL\n"
        "O Valor Presente Líquido desconta os fluxos futuros à taxa mínima de atratividade:\n"
        "$$\\text{VPL} = \\sum_{t=1}^n \\frac{FC_t}{(1 + r)^t} - I_0$$\n"
        "Projetos com VPL positivo agregam valor econômico à empresa.",
        fontsize=16,
    )

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_slugify_converts_text_to_valid_slug() -> None:
    """Tests that slugify handles accents, special characters, and casing properly.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    assert (
        slugify("Critérios de Decisão & Criação de Valor!")
        == "criterios-de-decisao-criacao-de-valor"
    )
    assert slugify("Aula 01: VPL / TIR") == "aula-01-vpl-tir"
    assert slugify("  Espaços   Extras  ") == "espacos-extras"


def test_pipeline_stops_before_humanizer_when_factual_blocker_remains(
    sample_syllabus_module: SyllabusModule, fake_llm_client: FakeLLMClient
) -> None:
    """A failed factual audit cannot reach humanization or produce an output."""
    state = create_initial_state(
        slides=[SlideChunk(slide_number=1, title="VPL", raw_text="Dados do slide.")],
        syllabus=sample_syllabus_module,
        lesson_number=1,
        lesson_title="VPL",
        source_slide_filename="aula.pdf",
    )
    issue = GuardrailIssue(
        claim_id="C1",
        quote="Afirmação falsa.",
        category="technical",
        verdict="false",
        severity="S1",
    )
    fake_llm_client.add_structured_response(
        DraftResult(raw_draft="Afirmação falsa.", extracted_zettels=[])
    )
    fake_llm_client.add_structured_response(GuardrailResponse(issues=[issue]))

    with pytest.raises(RuntimeError, match="auditoria factual"):
        run_lesson_pipeline(state=state, client=fake_llm_client)

    assert state.audit_items == [issue.to_claim_audit_item()]
    assert state.output is None
    assert state.humanized_markdown is None
    assert [call.call_type for call in fake_llm_client.calls] == ["structured", "structured"]


@pytest.mark.parametrize("artifact", ["lesson", "zettel"])
def test_pipeline_blocks_claim_introduced_by_humanizer(
    sample_syllabus_module: SyllabusModule, artifact: str
) -> None:
    """The final audit sees the exact rewritten lesson and atomic notes."""
    state = create_initial_state(
        slides=[SlideChunk(slide_number=1, title="VPL", raw_text="A taxa é 10%.")],
        syllabus=sample_syllabus_module,
        lesson_number=1,
        lesson_title="VPL",
        source_slide_filename="aula.pdf",
    )
    zettel_text = "A taxa é 20%." if artifact == "zettel" else "A taxa é 10%."
    lesson_text = "A taxa é 20%." if artifact == "lesson" else "A taxa é 10%."
    client = FakeLLMClient(
        structured_responses=[
            DraftResult(
                raw_draft="A taxa é 10%.",
                extracted_zettels=[
                    AtomicZettel(
                        slug="taxa",
                        title="Taxa",
                        domain_tags=[],
                        content_markdown=(
                            "A taxa é 10%. Um. Dois. Três. Quatro."
                            if artifact == "zettel"
                            else "A taxa é 10%."
                        ),
                        related_links=[],
                    )
                ],
            )
        ],
        text_responses=[lesson_text],
    )
    bad_claim = ClaimAuditItem(
        claim_id="C1",
        quote="A taxa é 20%.",
        category="metric",
        verdict="false",
        severity="S1",
        proposed_fix="A taxa é 10%.",
    )
    auditor = FakeLLMClient(
        structured_responses=[
            GuardrailResponse(issues=[]),
            AuditClaimsResponse(claims=[bad_claim]),
        ]
    )
    if artifact == "zettel":
        client.add_text_response(zettel_text)

    with pytest.raises(RuntimeError, match="auditoria factual"):
        run_lesson_pipeline(state=state, client=client, auditor_client=auditor)

    assert state.output is None
    assert state.fact_check_passed is False
    assert [item.audit_stage for item in state.audit_items] == ["final"]
    assert state.audit_items[-1].quote == "A taxa é 20%."
    assert len(auditor.calls) == 2
    assert lesson_text in auditor.calls[-1].user_prompt
    assert zettel_text in auditor.calls[-1].user_prompt


def test_pipeline_records_initial_and_final_audits(
    sample_syllabus_module: SyllabusModule,
) -> None:
    """The published text is the one sent to the final audit."""
    state = create_initial_state(
        slides=[SlideChunk(slide_number=1, title="VPL", raw_text="A taxa é 10%.")],
        syllabus=sample_syllabus_module,
        lesson_number=1,
        lesson_title="VPL",
        source_slide_filename="aula.pdf",
    )
    client = FakeLLMClient(
        structured_responses=[DraftResult(raw_draft="A taxa é 10%. Dado inventado.")],
        text_responses=["A taxa usada é 10%."],
    )
    auditor = FakeLLMClient(
        structured_responses=[
            GuardrailResponse(
                issues=[
                    GuardrailIssue(
                        claim_id="C1",
                        quote="Dado inventado.",
                        category="technical",
                        verdict="unsupported",
                        severity="S4",
                    )
                ]
            ),
            AuditClaimsResponse(
                claims=[
                    ClaimAuditItem(
                        claim_id="C2",
                        quote="A taxa usada é 10%.",
                        category="metric",
                        verdict="verified",
                        evidence_kind="slide",
                        evidence_locator=1,
                        evidence_quote="A taxa é 10%.",
                    )
                ]
            ),
        ]
    )

    output = run_lesson_pipeline(state=state, client=client, auditor_client=auditor)

    assert output.body_markdown == "A taxa usada é 10%."
    assert [item.audit_stage for item in output.audit_items] == ["draft", "final"]
    assert output.body_markdown in auditor.calls[-1].user_prompt


def test_pipeline_does_not_publish_when_final_auditor_fails(
    sample_syllabus_module: SyllabusModule,
) -> None:
    """An unavailable final auditor cannot result in an approved output."""
    state = create_initial_state(
        slides=[SlideChunk(slide_number=1, title="VPL", raw_text="A taxa é 10%.")],
        syllabus=sample_syllabus_module,
        lesson_number=1,
        lesson_title="VPL",
        source_slide_filename="aula.pdf",
    )
    client = FakeLLMClient(
        structured_responses=[DraftResult(raw_draft="A taxa é 10%.")],
        text_responses=["A taxa usada é 10%."],
    )
    auditor = FakeLLMClient(structured_responses=[GuardrailResponse(issues=[])])

    with pytest.raises(RuntimeError, match="No canned response"):
        run_lesson_pipeline(state=state, client=client, auditor_client=auditor)

    assert state.output is None
    assert not state.fact_check_passed


def test_find_syllabus_module_by_slug(sample_syllabus_module: SyllabusModule) -> None:
    """Tests finding a module in a StructuredSyllabus by discipline slug.

    Args:
        sample_syllabus_module: Sample syllabus module fixture.

    Returns:
        None.

    Raises:
        None.
    """
    structured = StructuredSyllabus(modules=[sample_syllabus_module])
    found = find_syllabus_module(structured, "financas-corporativas")
    assert found.discipline_name == "Finanças Corporativas"

    with pytest.raises(KeyError, match="financas-inexistente"):
        find_syllabus_module(structured, "financas-inexistente")


def test_ingestion_node_builds_initial_state(
    synthetic_graph_pdf_path: Path,
    sample_syllabus_module: SyllabusModule,
) -> None:
    """Tests ingestion_node parsing slides and populating initial LessonPipelineState.

    Args:
        synthetic_graph_pdf_path: Path to synthetic PDF slides.
        sample_syllabus_module: Sample syllabus module fixture.

    Returns:
        None.

    Raises:
        None.
    """
    state = ingestion_node(
        slide_path=synthetic_graph_pdf_path,
        syllabus=sample_syllabus_module,
        lesson_number=1,
        lesson_title="Critérios de Decisão",
    )

    assert isinstance(state, LessonPipelineState)
    assert state.discipline_slug == "financas-corporativas"
    assert state.discipline_name == "Finanças Corporativas"
    assert state.lesson_number == 1
    assert state.lesson_title == "Critérios de Decisão"
    assert state.lesson_slug == "criterios-de-decisao"
    assert state.source_slide_filename == "slides_aula_01.pdf"
    assert len(state.slides) == 2
    assert state.raw_draft is None
    assert state.audited_markdown is None
    assert state.humanized_markdown is None
    assert state.output is None


def test_create_initial_state_with_in_memory_slides(
    sample_syllabus_module: SyllabusModule,
) -> None:
    """Tests create_initial_state using pre-extracted SlideChunk objects.

    Args:
        sample_syllabus_module: Sample syllabus module fixture.

    Returns:
        None.

    Raises:
        None.
    """
    chunks = [
        SlideChunk(slide_number=1, title="Intro", raw_text="Conteúdo do slide 1"),
        SlideChunk(slide_number=2, title="VPL", raw_text="Conteúdo do slide 2"),
    ]
    state = create_initial_state(
        slides=chunks,
        syllabus=sample_syllabus_module,
        lesson_number=2,
        lesson_title="Análise de Fluxo",
        source_slide_filename="manual_input.pdf",
        lesson_slug="analise-fluxo-custom",
    )

    assert state.lesson_number == 2
    assert state.lesson_slug == "analise-fluxo-custom"
    assert state.source_slide_filename == "manual_input.pdf"
    assert len(state.slides) == 2


def test_run_lesson_pipeline_end_to_end_success(
    sample_syllabus_module: SyllabusModule,
    fake_llm_client: FakeLLMClient,
) -> None:
    """Tests complete end-to-end execution of the lesson pipeline returning WikiLessonOutput.

    Args:
        sample_syllabus_module: Sample syllabus module fixture.
        fake_llm_client: Mock LLM client fixture.

    Returns:
        None.

    Raises:
        None.
    """
    slides = [
        SlideChunk(
            slide_number=1,
            title="Critérios de Decisão",
            raw_text="O VPL desconta fluxos futuros à taxa de oportunidade.",
        )
    ]
    initial_state = create_initial_state(
        slides=slides,
        syllabus=sample_syllabus_module,
        lesson_number=1,
        lesson_title="Critérios de Decisão",
        source_slide_filename="aula_01.pdf",
    )

    # 1. Drafter response (DraftResult)
    draft_result = DraftResult(
        raw_draft=(
            "# Aula 01: Critérios de Decisão\n\n"
            "O método do VPL desconta fluxos de caixa futuros. "
            "Ele é considerado a regra de ouro das finanças."
        ),
        extracted_zettels=[
            AtomicZettel(
                slug="valor-presente-liquido",
                title="Valor Presente Líquido (VPL)",
                domain_tags=["financas", "avaliacao-projetos"],
                content_markdown="Definição do VPL como métrica de criação de valor.",
                related_links=["taxa-interna-retorno"],
            )
        ],
    )
    fake_llm_client.add_structured_response(draft_result)

    # 2. Guardrail response (GuardrailResponse)
    fake_llm_client.add_structured_response(GuardrailResponse(issues=[]))

    # 3. Humanizer response (clean prose string)
    clean_prose = (
        "# Aula 01: Critérios de Decisão\n\n"
        "O método do VPL desconta os fluxos de caixa futuros à taxa de oportunidade. "
        "A técnica orienta as decisões de investimento corporativo com critério analítico."
    )
    fake_llm_client.add_text_response(clean_prose)
    fake_llm_client.add_structured_response(AuditClaimsResponse(claims=[]))

    test_date = date(2026, 10, 18)
    output = run_lesson_pipeline(
        state=initial_state,
        client=fake_llm_client,
        processed_date=test_date,
    )

    assert isinstance(output, WikiLessonOutput)
    assert output.discipline_slug == "financas-corporativas"
    assert output.discipline_name == "Finanças Corporativas"
    assert output.lesson_number == 1
    assert output.lesson_title == "Critérios de Decisão"
    assert output.lesson_slug == "criterios-de-decisao"
    assert output.processed_date == test_date
    assert output.source_slide_filename == "aula_01.pdf"
    assert output.fact_check_passed is True
    assert output.removed_unsupported_claims == 0
    assert output.body_markdown == clean_prose
    assert len(output.extracted_zettels) == 1
    assert output.extracted_zettels[0].slug == "valor-presente-liquido"
    assert output.audit_items == []
    assert output.cross_links == []
    assert output.detected_tensions == []

    # Verify that initial_state was updated and output attribute is assigned
    assert initial_state.output is output
    assert initial_state.humanized_markdown == clean_prose
    assert initial_state.humanizer_retry_count == 1
    assert len(fake_llm_client.calls) == 4


def test_execute_pipeline_remediates_unsupported_claims(
    sample_syllabus_module: SyllabusModule,
    fake_llm_client: FakeLLMClient,
) -> None:
    """Tests that execute_pipeline purges unsupported S4 claims and updates metrics.

    Args:
        sample_syllabus_module: Sample syllabus module fixture.
        fake_llm_client: Mock LLM client fixture.

    Returns:
        None.

    Raises:
        None.
    """
    slides = [SlideChunk(slide_number=1, title="VPL", raw_text="Texto do slide.")]
    initial_state = create_initial_state(
        slides=slides,
        syllabus=sample_syllabus_module,
        lesson_number=1,
        lesson_title="Critérios de Decisão",
        source_slide_filename="aula_01.pdf",
    )

    # 1. Drafter response with an unsupported claim
    flawed_draft = (
        "O método do VPL é a base das decisões. "
        "A empresa XYZ aumentou seus lucros em 800% após adotar o VPL em 1920."
    )
    fake_llm_client.add_structured_response(DraftResult(raw_draft=flawed_draft))

    # 2. Guardrail response flagging S4
    audit_response = GuardrailResponse(
        issues=[
            GuardrailIssue(
                claim_id="CLM-001",
                quote="A empresa XYZ aumentou seus lucros em 800% após adotar o VPL em 1920.",
                category="metric",
                verdict="unsupported",
                severity="S4",
                reason="Nenhum slide menciona a empresa XYZ ou 1920.",
            )
        ]
    )
    fake_llm_client.add_structured_response(audit_response)

    # 3. Humanizer response on the audited prose
    clean_humanized = (
        "O método do VPL constitui a base analítica das decisões de alocação de capital."
    )
    fake_llm_client.add_text_response(clean_humanized)
    fake_llm_client.add_structured_response(AuditClaimsResponse(claims=[]))

    final_state = execute_pipeline(state=initial_state, client=fake_llm_client)

    assert final_state.fact_check_passed is True
    assert final_state.removed_unsupported_claims == 1
    assert final_state.output is not None
    assert final_state.output.removed_unsupported_claims == 1
    assert final_state.output.body_markdown == clean_humanized
    assert "XYZ" not in final_state.output.body_markdown


def test_run_lesson_pipeline_aborts_on_humanizer_failure(
    sample_syllabus_module: SyllabusModule,
    fake_llm_client: FakeLLMClient,
) -> None:
    """Tests that run_lesson_pipeline raises HumanizerValidationError if humanizer fails.

    Args:
        sample_syllabus_module: Sample syllabus module fixture.
        fake_llm_client: Mock LLM client fixture.

    Returns:
        None.

    Raises:
        None.
    """
    slides = [SlideChunk(slide_number=1, title="VPL", raw_text="Texto do slide.")]
    initial_state = create_initial_state(
        slides=slides,
        syllabus=sample_syllabus_module,
        lesson_number=1,
        lesson_title="Critérios de Decisão",
        source_slide_filename="aula_01.pdf",
    )

    draft_result = DraftResult(raw_draft="Texto com rascunho de aula.")
    fake_llm_client.add_structured_response(draft_result)

    audit_response = GuardrailResponse(issues=[])
    fake_llm_client.add_structured_response(audit_response)

    # 3 persistent bad attempts with an em-dash to trigger HumanizerValidationError
    bad_attempt = "Texto com travessão — infração proibida pelo linter."
    fake_llm_client.add_text_response(bad_attempt)
    fake_llm_client.add_text_response(bad_attempt)
    fake_llm_client.add_text_response(bad_attempt)

    with pytest.raises(HumanizerValidationError, match="Humanizer exceeded maximum attempts"):
        run_lesson_pipeline(state=initial_state, client=fake_llm_client)

    assert initial_state.output is None


def test_create_initial_state_empty_slides_raises(sample_syllabus_module: SyllabusModule) -> None:
    """Tests that create_initial_state raises ValueError when slides list is empty.

    Args:
        sample_syllabus_module: Sample syllabus module fixture.

    Returns:
        None.

    Raises:
        None.
    """
    with pytest.raises(ValueError, match="Cannot initialize pipeline state with empty slides list"):
        create_initial_state(
            slides=[],
            syllabus=sample_syllabus_module,
            lesson_number=1,
            lesson_title="Aula 01",
            source_slide_filename="aula.pdf",
        )


def test_ingestion_node_missing_slide_file_raises(
    tmp_path: Path,
    sample_syllabus_module: SyllabusModule,
) -> None:
    """Tests that ingestion_node raises FileNotFoundError when presentation file does not exist.

    Args:
        tmp_path: Pytest temporary directory fixture.
        sample_syllabus_module: Sample syllabus module fixture.

    Returns:
        None.

    Raises:
        None.
    """
    missing_file = tmp_path / "missing_slides.pdf"
    with pytest.raises(FileNotFoundError, match="Slide file not found"):
        ingestion_node(
            slide_path=missing_file,
            syllabus=sample_syllabus_module,
            lesson_number=1,
        )


def test_ingestion_node_infers_title_when_omitted(
    synthetic_graph_pdf_path: Path,
    sample_syllabus_module: SyllabusModule,
) -> None:
    """Tests that ingestion_node automatically infers title and slug when title is omitted.

    Args:
        synthetic_graph_pdf_path: Path to synthetic presentation PDF fixture.
        sample_syllabus_module: Sample syllabus module fixture.

    Returns:
        None.

    Raises:
        None.
    """
    state = ingestion_node(
        slide_path=synthetic_graph_pdf_path,
        syllabus=sample_syllabus_module,
        lesson_number=1,
        lesson_title=None,
    )
    assert "Finanças Corporativas" in state.lesson_title
    assert state.lesson_slug != ""


def test_ingestion_node_with_full_syllabus(
    synthetic_graph_pdf_path: Path,
    sample_syllabus_module: SyllabusModule,
) -> None:
    """Tests that ingestion_node accepts and stores full_syllabus on pipeline state.

    Args:
        synthetic_graph_pdf_path: Path to synthetic presentation PDF fixture.
        sample_syllabus_module: Sample syllabus module fixture.

    Returns:
        None.

    Raises:
        None.
    """
    full_syllabus = StructuredSyllabus(modules=[sample_syllabus_module])
    state = ingestion_node(
        slide_path=synthetic_graph_pdf_path,
        syllabus=sample_syllabus_module,
        full_syllabus=full_syllabus,
        lesson_number=1,
    )
    assert state.full_syllabus is not None
    assert len(state.full_syllabus.modules) == 1
    assert state.full_syllabus.modules[0].discipline_slug == "financas-corporativas"


def test_run_lesson_pipeline_propagates_tensions_to_output(
    sample_syllabus_module: SyllabusModule,
    fake_llm_client: FakeLLMClient,
) -> None:
    """Tests that tensions and cross-links generated during drafting reach WikiLessonOutput.

    Args:
        sample_syllabus_module: Sample syllabus module fixture.
        fake_llm_client: Fake LLM client fixture.

    Returns:
        None.

    Raises:
        None.
    """
    from cathedra.schemas import CrossDisciplineLink, DialecticalTension

    slide = SlideChunk(
        slide_number=1,
        title="VPL e Payback",
        raw_text="Critérios de investimento.",
    )
    pipeline_state = create_initial_state(
        slides=[slide],
        syllabus=sample_syllabus_module,
        lesson_number=1,
        lesson_title="Critérios de Investimento",
        source_slide_filename="aula_01.pdf",
    )

    link = CrossDisciplineLink(
        target_discipline_slug="estrategia",
        target_topic="Vantagem Competitiva",
        connection_type="synergy",
        description="Alinhamento entre VPL e vantagem sustentável.",
    )
    tension = DialecticalTension(
        slug="vpl-vs-payback",
        title="VPL vs Payback",
        pole_a_discipline="financas",
        pole_a_framework="VPL",
        pole_a_thesis="Maximizar valor econômico a longo prazo.",
        pole_b_discipline="financas",
        pole_b_framework="Payback",
        pole_b_thesis="Recuperação rápida de liquidez no curto prazo.",
        tension_nature="Valor vs Liquidez",
        synthesis_guidelines="Usar VPL como corte e payback como filtro de risco de liquidez.",
    )

    draft_result = DraftResult(
        raw_draft="O método do VPL orienta a alocação ótima de capital.",
        cross_links=[link],
        detected_tensions=[tension],
    )
    fake_llm_client.add_structured_response(draft_result)

    audit_response = GuardrailResponse(issues=[])
    fake_llm_client.add_structured_response(audit_response)

    clean_humanized = "O método do VPL orienta a alocação ótima de capital."
    fake_llm_client.add_text_response(clean_humanized)
    fake_llm_client.add_structured_response(AuditClaimsResponse(claims=[]))

    output = run_lesson_pipeline(state=pipeline_state, client=fake_llm_client)

    assert len(output.cross_links) == 1
    assert output.cross_links[0].target_discipline_slug == "estrategia"
    assert len(output.detected_tensions) == 1
    assert output.detected_tensions[0].slug == "vpl-vs-payback"


def test_pipeline_with_transcript(
    synthetic_graph_pdf_path: Path,
    sample_syllabus_module: SyllabusModule,
    fake_llm_client: FakeLLMClient,
    tmp_path: Path,
) -> None:
    """Tests end-to-end pipeline execution with multimodal audio transcript integration.

    Args:
        synthetic_graph_pdf_path: Synthetic PDF slides fixture.
        sample_syllabus_module: Standard syllabus module fixture.
        fake_llm_client: Mock LLM client fixture.
        tmp_path: Temporary directory fixture.

    Returns:
        None.

    Raises:
        None.
    """
    from datetime import UTC, datetime

    from cathedra.schemas import VideoTranscript

    transcript = VideoTranscript(
        source_filename="Aula_01_Financas.mp4",
        discipline_slug=sample_syllabus_module.discipline_slug,
        duration_seconds=3600.0,
        model_name="large-v3",
        compute_type="int8_float16",
        processed_at=datetime.now(UTC),
        full_text_raw="Texto gravado da aula",
        full_text_cleaned="O professor explicou que o VPL é a regra soberana de decisão.",
        segments=[],
    )

    transcript_file = tmp_path / "Aula_01_Financas.json"
    transcript_file.write_text(transcript.model_dump_json(indent=2), encoding="utf-8")

    state = ingestion_node(
        slide_path=synthetic_graph_pdf_path,
        syllabus=sample_syllabus_module,
        lesson_number=1,
        transcript_path=transcript_file,
    )
    assert state.transcript is not None
    assert state.transcript.source_filename == "Aula_01_Financas.mp4"

    draft_result = DraftResult(
        raw_draft="O método do VPL orienta a alocação ótima de capital.",
    )
    fake_llm_client.add_structured_response(draft_result)

    audit_response = GuardrailResponse(issues=[])
    fake_llm_client.add_structured_response(audit_response)

    clean_humanized = "O método do VPL orienta a alocação ótima de capital."
    fake_llm_client.add_text_response(clean_humanized)
    fake_llm_client.add_structured_response(AuditClaimsResponse(claims=[]))

    output = run_lesson_pipeline(state=state, client=fake_llm_client)

    assert output.source_transcript_filename == "Aula_01_Financas.mp4"


def test_execute_pipeline_final_stage_uses_invariance_without_transcript_payload(
    fake_llm_client: FakeLLMClient,
) -> None:
    """Final audit stage compares humanized text against audited prose without raw transcript."""
    from datetime import UTC, datetime

    from cathedra.agents.graph import create_initial_state, execute_pipeline
    from cathedra.schemas import (
        AuditClaimsResponse,
        DraftResult,
        SlideChunk,
        SyllabusModule,
        TranscriptSegment,
        VideoTranscript,
    )

    syllabus = SyllabusModule(
        discipline_slug="estatistica",
        discipline_name="Estatística",
        syllabus_summary="Base.",
        topics=["Média"],
        bibliography=[],
    )
    slides = [SlideChunk(slide_number=1, title="Média", raw_text="A média é a soma sobre n.")]
    transcript = VideoTranscript(
        source_filename="aula01.mp4",
        discipline_slug="estatistica",
        lesson_number=1,
        duration_seconds=60.0,
        model_name="large-v3",
        compute_type="int8_float16",
        processed_at=datetime(2026, 11, 9, 2, 0, tzinfo=UTC),
        full_text_raw="marcador-unico-transcricao",
        full_text_cleaned="marcador-unico-transcricao",
        segments=[
            TranscriptSegment(
                id=1,
                start=0.0,
                end=5.0,
                text_raw="marcador-unico-transcricao",
                text_cleaned="marcador-unico-transcricao",
            )
        ],
    )
    state = create_initial_state(
        slides=slides,
        syllabus=syllabus,
        lesson_number=1,
        lesson_title="Média",
        source_slide_filename="aula.pdf",
        transcript=transcript,
    )

    fake_llm_client.add_structured_response(
        DraftResult(raw_draft="A média é a soma sobre n.", extracted_zettels=[])
    )
    fake_llm_client.add_structured_response(GuardrailResponse(issues=[]))
    fake_llm_client.add_text_response("Calcula-se a média pela soma dividida por n.")
    fake_llm_client.add_structured_response(AuditClaimsResponse(claims=[]))

    result_state = execute_pipeline(state=state, client=fake_llm_client)
    assert result_state.fact_check_passed is True
    final_call = fake_llm_client.calls[-1]
    assert "Texto Auditado (Referência Aprovada)" in final_call.user_prompt
    assert "marcador-unico-transcricao" not in final_call.user_prompt


def test_finalize_output_node_rejects_missing_audited_and_humanized_markdown(
    sample_syllabus_module: SyllabusModule,
) -> None:
    """Tests that finalize_output_node never falls back silently to unaudited raw_draft.

    Args:
        sample_syllabus_module: Sample syllabus module fixture.

    Returns:
        None.

    Raises:
        None.
    """
    from cathedra.agents.graph import finalize_output_node

    state = create_initial_state(
        slides=[SlideChunk(slide_number=1, title="VPL", raw_text="VPL > 0")],
        syllabus=sample_syllabus_module,
        lesson_number=1,
        lesson_title="VPL",
        source_slide_filename="aula.pdf",
    )
    state.raw_draft = "Rascunho não auditado."

    with pytest.raises(ValueError, match="without audited or humanized markdown"):
        finalize_output_node(state)
