"""Unit tests for Pydantic v2 data contracts.

Validates instantiation, serialization, defaults, and validation errors for all schemas
defined in Section 3 of SPEC.md.
"""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from mba_wiki.schemas import (
    AtomicZettel,
    AuditClaimsResponse,
    ClaimAuditItem,
    CrossDisciplineLink,
    DialecticalTension,
    DraftResult,
    FactCheckResult,
    HumanizerResult,
    LessonAuditReport,
    LessonPipelineState,
    SlideChunk,
    StructuredSyllabus,
    SyllabusModule,
    TranscriptSegment,
    VideoTranscript,
    WikiLessonOutput,
)


def test_syllabus_module_valid() -> None:
    """Tests successful instantiation and serialization of SyllabusModule.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    module = SyllabusModule(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        professor="Dr. Carlos Silva",
        syllabus_summary="Introdução às decisões financeiras de longo prazo.",
        topics=["VPL", "TIR", "Custo de Capital"],
        bibliography=["Brealey, Myers. Princípios de Finanças Corporativas."],
    )
    assert module.discipline_slug == "financas-corporativas"
    assert module.discipline_name == "Finanças Corporativas"
    assert module.professor == "Dr. Carlos Silva"
    assert len(module.topics) == 3
    assert len(module.bibliography) == 1

    dumped = module.model_dump()
    restored = SyllabusModule.model_validate(dumped)
    assert restored == module


def test_syllabus_module_defaults_and_validation() -> None:
    """Tests SyllabusModule optional default values and rejection of missing fields.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    module = SyllabusModule(
        discipline_slug="gestao-estrategica",
        discipline_name="Gestão Estratégica",
        syllabus_summary="Análise de cenários e vantagem competitiva.",
        topics=["5 Forças de Porter", "RBV"],
        bibliography=["Porter, M. Estratégia Competitiva."],
    )
    assert module.professor is None

    with pytest.raises(ValidationError):
        SyllabusModule.model_validate(
            {
                "discipline_slug": "gestao-estrategica",
                # missing discipline_name, syllabus_summary, topics, bibliography
            }
        )


def test_structured_syllabus_valid() -> None:
    """Tests successful instantiation and serialization of StructuredSyllabus.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    module = SyllabusModule(
        discipline_slug="mkt-digital",
        discipline_name="Marketing Digital",
        syllabus_summary="Growth e canais digitais.",
        topics=["SEO", "CAC", "LTV"],
        bibliography=["Kotler, P. Marketing 4.0."],
    )
    syllabus = StructuredSyllabus(modules=[module])
    assert len(syllabus.modules) == 1
    assert syllabus.modules[0].discipline_slug == "mkt-digital"

    json_data = syllabus.model_dump_json()
    restored = StructuredSyllabus.model_validate_json(json_data)
    assert restored.modules[0].discipline_name == "Marketing Digital"


def test_structured_syllabus_validation_error() -> None:
    """Tests rejection of invalid modules data in StructuredSyllabus.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    with pytest.raises(ValidationError):
        StructuredSyllabus.model_validate({"modules": "not-a-list"})


def test_slide_chunk_valid_and_defaults() -> None:
    """Tests SlideChunk with default values and custom fields.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    chunk_defaults = SlideChunk(
        slide_number=1,
        title="Introdução ao VPL",
        raw_text="O Valor Presente Líquido desconta os fluxos de caixa futuros.",
    )
    assert chunk_defaults.slide_number == 1
    assert chunk_defaults.latex_equations == []
    assert chunk_defaults.visual_descriptions == []

    chunk_full = SlideChunk(
        slide_number=2,
        title="Fórmula do VPL",
        raw_text="Fórmula matemática do VPL a seguir.",
        latex_equations=[r"VPL = \sum_{t=1}^n \frac{FC_t}{(1+k)^t} - I_0"],
        visual_descriptions=["Gráfico de linha mostrando ponto de equilíbrio"],
    )
    assert len(chunk_full.latex_equations) == 1
    assert len(chunk_full.visual_descriptions) == 1

    restored = SlideChunk.model_validate(chunk_full.model_dump())
    assert restored == chunk_full


def test_slide_chunk_validation_error() -> None:
    """Tests rejection of invalid types in SlideChunk.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    with pytest.raises(ValidationError):
        SlideChunk.model_validate(
            {
                "slide_number": "invalid_number",
                "title": "Slide Errado",
                "raw_text": "Texto",
            }
        )


def test_claim_audit_item_valid_and_literals() -> None:
    """Tests ClaimAuditItem valid literals and optional default values.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    item = ClaimAuditItem(
        claim_id="CLM-001",
        quote="A taxa Selic média em 2021 foi 4,40%.",
        category="metric",
        verdict="verified",
        severity="S6",
        evidence_source="Banco Central do Brasil",
        proposed_fix=None,
    )
    assert item.claim_id == "CLM-001"
    assert item.category == "metric"
    assert item.verdict == "verified"
    assert item.severity == "S6"

    item_defaults = ClaimAuditItem(
        claim_id="CLM-002",
        quote="A fórmula de Black-Scholes foi proposta em 1973.",
        category="formula",
        verdict="verified",
    )
    assert item_defaults.severity is None
    assert item_defaults.evidence_source is None
    assert item_defaults.proposed_fix is None


@pytest.mark.parametrize(
    "invalid_data",
    [
        {
            "claim_id": "CLM-ERR",
            "quote": "Citação",
            "category": "invalid_category",
            "verdict": "verified",
        },
        {
            "claim_id": "CLM-ERR",
            "quote": "Citação",
            "category": "formula",
            "verdict": "invalid_verdict",
        },
        {
            "claim_id": "CLM-ERR",
            "quote": "Citação",
            "category": "formula",
            "verdict": "verified",
            "severity": "S7",
        },
    ],
)
def test_claim_audit_item_invalid_literals(invalid_data: dict[str, str]) -> None:
    """Tests rejection of invalid categories, verdicts, and severities in ClaimAuditItem.

    Args:
        invalid_data: Dictionary containing fields with invalid literal values.

    Returns:
        None.

    Raises:
        None.
    """
    with pytest.raises(ValidationError):
        ClaimAuditItem.model_validate(invalid_data)


def test_atomic_zettel_valid_and_serialization() -> None:
    """Tests AtomicZettel instantiation and dict/json serialization.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    zettel = AtomicZettel(
        slug="valor-presente-liquido",
        title="Valor Presente Líquido (VPL)",
        domain_tags=["financas", "valuation"],
        content_markdown="# VPL\n\nMétrica fundamental de análise de investimentos.",
        related_links=["taxa-interna-retorno", "custo-medio-ponderado-capital"],
    )
    assert zettel.slug == "valor-presente-liquido"
    assert zettel.domain_tags == ["financas", "valuation"]
    assert len(zettel.related_links) == 2

    restored = AtomicZettel.model_validate_json(zettel.model_dump_json())
    assert restored == zettel


def test_atomic_zettel_validation_error() -> None:
    """Tests rejection of missing mandatory fields in AtomicZettel.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    with pytest.raises(ValidationError):
        AtomicZettel.model_validate({"slug": "apenas-slug"})


def test_wiki_lesson_output_valid_and_defaults() -> None:
    """Tests WikiLessonOutput instantiation, nested models, and defaults.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    zettel = AtomicZettel(
        slug="vpl-conceito",
        title="Conceito de VPL",
        domain_tags=["financas"],
        content_markdown="Conteúdo sobre VPL.",
        related_links=[],
    )
    audit_item = ClaimAuditItem(
        claim_id="CLM-001",
        quote="Afirmação auditada",
        category="technical",
        verdict="verified",
    )
    output = WikiLessonOutput(
        discipline_slug="financas",
        discipline_name="Finanças",
        lesson_number=1,
        lesson_title="Introdução ao VPL",
        lesson_slug="introducao-ao-vpl",
        processed_date=date(2026, 10, 18),
        source_slide_filename="aula_01.pdf",
        fact_check_passed=True,
        removed_unsupported_claims=0,
        body_markdown="## Aula 01\n\nTexto formatado da aula.",
        extracted_zettels=[zettel],
        audit_items=[audit_item],
    )
    assert output.discipline_slug == "financas"
    assert output.lesson_number == 1
    assert output.processed_date == date(2026, 10, 18)
    assert len(output.extracted_zettels) == 1
    assert len(output.audit_items) == 1

    # Test default audit_items
    output_no_audits = WikiLessonOutput(
        discipline_slug="financas",
        discipline_name="Finanças",
        lesson_number=2,
        lesson_title="TIR",
        lesson_slug="tir",
        processed_date=date(2026, 10, 18),
        source_slide_filename="aula_02.pdf",
        fact_check_passed=True,
        removed_unsupported_claims=0,
        body_markdown="Texto",
        extracted_zettels=[],
    )
    assert output_no_audits.audit_items == []


def test_lesson_audit_report_valid_and_defaults() -> None:
    """Tests LessonAuditReport instantiation, fields, and default audit_items.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    report = LessonAuditReport(
        discipline_slug="financas",
        discipline_name="Finanças",
        lesson_number=1,
        lesson_title="Introdução ao VPL",
        processed_date=date(2026, 10, 18),
        fact_check_passed=True,
        total_claims_audited=5,
        removed_unsupported_claims=1,
    )
    assert report.total_claims_audited == 5
    assert report.removed_unsupported_claims == 1
    assert report.audit_items == []

    restored = LessonAuditReport.model_validate(report.model_dump())
    assert restored == report


def test_lesson_pipeline_state_valid_and_defaults() -> None:
    """Tests LessonPipelineState instantiation with mandatory fields and default state.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    syllabus = SyllabusModule(
        discipline_slug="financas",
        discipline_name="Finanças",
        syllabus_summary="Resumo da ementa.",
        topics=["VPL"],
        bibliography=["Livro"],
    )
    slide = SlideChunk(
        slide_number=1,
        title="Slide 1",
        raw_text="Conteúdo",
    )
    state = LessonPipelineState(
        discipline_slug="financas",
        discipline_name="Finanças",
        lesson_number=1,
        lesson_title="Aula 01",
        lesson_slug="aula-01",
        source_slide_filename="slides_aula1.pdf",
        slides=[slide],
        syllabus=syllabus,
    )

    assert state.raw_draft is None
    assert state.extracted_zettels == []
    assert state.audit_items == []
    assert state.fact_check_passed is False
    assert state.removed_unsupported_claims == 0
    assert state.audited_markdown is None
    assert state.humanized_markdown is None
    assert state.humanizer_retry_count == 0
    assert state.output is None


def test_draft_result_valid_and_defaults() -> None:
    """Tests successful instantiation, defaults, and validation of DraftResult.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    draft = DraftResult(raw_draft="Capítulo explicativo da aula.")
    assert draft.raw_draft == "Capítulo explicativo da aula."
    assert draft.extracted_zettels == []

    zettel = AtomicZettel(
        slug="vpl",
        title="VPL",
        domain_tags=["financas"],
        content_markdown="Nota conceitual de VPL.",
        related_links=[],
    )
    draft_with_zettels = DraftResult(
        raw_draft="Aula com links.",
        extracted_zettels=[zettel],
    )
    assert len(draft_with_zettels.extracted_zettels) == 1

    dumped = draft_with_zettels.model_dump()
    restored = DraftResult.model_validate(dumped)
    assert restored == draft_with_zettels

    with pytest.raises(ValidationError):
        DraftResult.model_validate({})


def test_audit_claims_response_and_fact_check_result() -> None:
    """Tests instantiation and defaults for AuditClaimsResponse and FactCheckResult.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    claim = ClaimAuditItem(
        claim_id="c1",
        quote="Trecho auditado.",
        category="formula",
        verdict="verified",
    )
    response = AuditClaimsResponse(claims=[claim])
    assert len(response.claims) == 1
    assert response.claims[0].claim_id == "c1"

    empty_response = AuditClaimsResponse()
    assert empty_response.claims == []

    result = FactCheckResult(
        audit_items=[claim],
        fact_check_passed=True,
        removed_unsupported_claims=0,
        audited_markdown="Texto limpo e aprovado.",
    )
    assert result.fact_check_passed is True
    assert result.removed_unsupported_claims == 0
    assert result.audited_markdown == "Texto limpo e aprovado."

    dumped = result.model_dump()
    restored = FactCheckResult.model_validate(dumped)
    assert restored == result


def test_humanizer_result_valid_and_defaults() -> None:
    """Tests successful instantiation and validation of HumanizerResult.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    result = HumanizerResult(
        humanized_text="Texto acadêmico polido.",
        retry_count=2,
        is_valid=True,
    )
    assert result.humanized_text == "Texto acadêmico polido."
    assert result.retry_count == 2
    assert result.is_valid is True

    dumped = result.model_dump()
    restored = HumanizerResult.model_validate(dumped)
    assert restored == result

    with pytest.raises(ValidationError):
        HumanizerResult.model_validate({})


def test_cross_discipline_link_valid() -> None:
    """Tests successful instantiation, validation, and serialization of CrossDisciplineLink.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    link = CrossDisciplineLink(
        target_discipline_slug="financas-corporativas",
        target_topic="Ciclo de Conversao de Caixa",
        connection_type="impact",
        description="A politica de estoques Just-in-Time afeta a necessidade de capital de giro.",
    )
    assert link.target_discipline_slug == "financas-corporativas"
    assert link.target_topic == "Ciclo de Conversao de Caixa"
    assert link.connection_type == "impact"
    assert "capital de giro" in link.description

    dumped = link.model_dump()
    restored = CrossDisciplineLink.model_validate(dumped)
    assert restored == link


def test_cross_discipline_link_validation_errors() -> None:
    """Tests validation constraints and rejected types for CrossDisciplineLink.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    with pytest.raises(ValidationError):
        # Invalid connection_type
        CrossDisciplineLink(
            target_discipline_slug="financas",
            target_topic="VPL",
            connection_type="invalid_type",  # type: ignore[arg-type]
            description="Descricao invalida.",
        )

    with pytest.raises(ValidationError):
        # Missing required fields
        CrossDisciplineLink.model_validate({"target_discipline_slug": "financas"})


def test_dialectical_tension_valid_and_defaults() -> None:
    """Tests successful instantiation and default list handling of DialecticalTension.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    tension = DialecticalTension(
        slug="eficiencia-vs-resiliencia",
        title="Eficiência Operacional vs Resiliência de Suprimentos",
        pole_a_discipline="gestao-de-operacoes",
        pole_a_framework="Lean / Just-in-Time",
        pole_a_thesis="Minimizar estoques e variabilidade para maximizar giro de capital.",
        pole_b_discipline="gestao-estrategica",
        pole_b_framework="Resiliência da Cadeia e Teoria de Opções",
        pole_b_thesis=(
            "Manter estoques de segurança e múltiplos fornecedores para absorver choques."
        ),
        tension_nature="Eficiência de Curto Prazo vs Sobrevivência e Continuidade",
        synthesis_guidelines=(
            "Adotar estoques estratégicos para componentes críticos (dual sourcing)."
        ),
    )
    assert tension.slug == "eficiencia-vs-resiliencia"
    assert tension.related_zettel_slugs == []

    dumped = tension.model_dump()
    restored = DialecticalTension.model_validate(dumped)
    assert restored == tension


def test_dialectical_tension_with_zettels_and_validation() -> None:
    """Tests DialecticalTension with populated zettel links and validation rejection.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    tension = DialecticalTension(
        slug="dcf-vs-opcoes-reais",
        title="Valuation por DCF vs Teoria de Opções Reais",
        pole_a_discipline="financas",
        pole_a_framework="DCF (Fluxo de Caixa Descontado)",
        pole_a_thesis="Rejeitar projetos com VPL negativo calculado no horizonte determinístico.",
        pole_b_discipline="inovacao",
        pole_b_framework="Opções Reais de Crescimento",
        pole_b_thesis=(
            "Projetos inovadores contêm opções de expansão que o DCF tradicional subavalia."
        ),
        tension_nature="Rigor Analítico vs Flexibilidade Estratégica em Alta Incerteza",
        synthesis_guidelines=(
            "Usar DCF para negócios maduros e Opções Reais para P&D em estágios iniciais."
        ),
        related_zettel_slugs=["valor-presente-liquido", "teoria-opcoes-reais"],
    )
    assert len(tension.related_zettel_slugs) == 2

    with pytest.raises(ValidationError):
        # Missing required field
        DialecticalTension.model_validate({"slug": "incompleto"})


def test_draft_result_with_cross_links_and_tensions() -> None:
    """Tests DraftResult extension supporting cross_links and detected_tensions.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    link = CrossDisciplineLink(
        target_discipline_slug="marketing",
        target_topic="Precificacao e Elasticidade",
        connection_type="synergy",
        description="A margem de contribuicao define o piso de precos do Marketing.",
    )
    tension = DialecticalTension(
        slug="lucro-curto-prazo-vs-marca",
        title="Margem Imediata vs Construção de Marca",
        pole_a_discipline="controladoria",
        pole_a_framework="Orçamento Base Zero",
        pole_a_thesis="Cortar verbas discricionárias para atingir EBITDA trimestral.",
        pole_b_discipline="marketing",
        pole_b_framework="Brand Equity",
        pole_b_thesis="Cortes em publicidade deterioram o valor intangível no longo prazo.",
        tension_nature="Metas Trimestrais vs Sustentabilidade de Marca",
        synthesis_guidelines=(
            "Proteger percentual fixo de receita para branding e amortizar como investimento."
        ),
    )
    draft = DraftResult(
        raw_draft="Rascunho rico com pontes e dilemas.",
        cross_links=[link],
        detected_tensions=[tension],
    )
    assert len(draft.cross_links) == 1
    assert len(draft.detected_tensions) == 1

    # Verify backward compatibility when omitting new fields
    legacy_draft = DraftResult(raw_draft="Apenas o rascunho legado.")
    assert legacy_draft.cross_links == []
    assert legacy_draft.detected_tensions == []


def test_wiki_lesson_output_with_cross_links_and_tensions() -> None:
    """Tests WikiLessonOutput extension supporting cross_links and detected_tensions.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    output = WikiLessonOutput(
        discipline_slug="operacoes",
        discipline_name="Gestão de Operações",
        lesson_number=1,
        lesson_title="Lean Manufacturing",
        lesson_slug="lean-manufacturing",
        processed_date=date(2026, 10, 19),
        source_slide_filename="aula01.pdf",
        fact_check_passed=True,
        removed_unsupported_claims=0,
        body_markdown="Corpo da aula.",
        extracted_zettels=[],
        cross_links=[],
        detected_tensions=[],
    )
    assert output.cross_links == []
    assert output.detected_tensions == []

    dumped = output.model_dump()
    restored = WikiLessonOutput.model_validate(dumped)
    assert restored == output


def test_lesson_pipeline_state_with_cross_links_and_tensions() -> None:
    """Tests LessonPipelineState extension supporting cross_links and detected_tensions.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    module = SyllabusModule(
        discipline_slug="operacoes",
        discipline_name="Gestão de Operações",
        syllabus_summary="Resumo de operações.",
        topics=["Lean", "Six Sigma"],
        bibliography=["Slack. Administração da Produção."],
    )
    state = LessonPipelineState(
        discipline_slug="operacoes",
        discipline_name="Gestão de Operações",
        lesson_number=1,
        lesson_title="Lean",
        lesson_slug="lean",
        source_slide_filename="slides.pdf",
        slides=[],
        syllabus=module,
    )
    assert state.cross_links == []
    assert state.detected_tensions == []


def test_transcript_segment_valid() -> None:
    """Tests successful instantiation, validation and serialization of TranscriptSegment.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    segment = TranscriptSegment(
        id=1,
        start=10.5,
        end=15.2,
        text_raw="É... bom dia a todos, hoje veremos CAPM.",
        text_cleaned="Bom dia a todos, hoje veremos CAPM.",
    )
    assert segment.id == 1
    assert segment.start == 10.5
    assert segment.end == 15.2
    assert segment.text_raw == "É... bom dia a todos, hoje veremos CAPM."
    assert segment.text_cleaned == "Bom dia a todos, hoje veremos CAPM."

    dumped = segment.model_dump()
    restored = TranscriptSegment.model_validate(dumped)
    assert restored == segment


def test_transcript_segment_invalid_timestamps() -> None:
    """Tests rejection of invalid start or end timestamps in TranscriptSegment.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    with pytest.raises(ValidationError):
        # end before start
        TranscriptSegment(
            id=1,
            start=20.0,
            end=10.0,
            text_raw="Texto",
            text_cleaned="Texto",
        )

    with pytest.raises(ValidationError):
        # negative start
        TranscriptSegment(
            id=1,
            start=-1.0,
            end=10.0,
            text_raw="Texto",
            text_cleaned="Texto",
        )


def test_video_transcript_valid() -> None:
    """Tests successful instantiation, defaults and round-trip serialization of VideoTranscript.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    now = datetime.now(UTC)
    segment = TranscriptSegment(
        id=1,
        start=0.0,
        end=5.0,
        text_raw="Iniciando a aula.",
        text_cleaned="Iniciando a aula.",
    )
    transcript = VideoTranscript(
        source_filename="Aula_01_Estrategia.mp4",
        discipline_slug="estrategia-competitiva",
        duration_seconds=10800.0,
        model_name="large-v3",
        compute_type="int8_float16",
        processed_at=now,
        full_text_raw="Iniciando a aula.",
        full_text_cleaned="Iniciando a aula.",
        segments=[segment],
    )
    assert transcript.source_filename == "Aula_01_Estrategia.mp4"
    assert transcript.discipline_slug == "estrategia-competitiva"
    assert transcript.duration_seconds == 10800.0
    assert len(transcript.segments) == 1
    assert transcript.segments[0].id == 1

    dumped = transcript.model_dump()
    restored = VideoTranscript.model_validate(dumped)
    assert restored.source_filename == transcript.source_filename
    assert restored.segments == transcript.segments


def test_video_transcript_invalid_duration() -> None:
    """Tests rejection of negative duration_seconds in VideoTranscript.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    with pytest.raises(ValidationError):
        VideoTranscript(
            source_filename="Aula_01.mp4",
            discipline_slug="financas",
            duration_seconds=-10.0,
            model_name="large-v3",
            compute_type="int8_float16",
            processed_at=datetime.now(UTC),
            full_text_raw="Texto",
            full_text_cleaned="Texto",
        )


def test_lesson_pipeline_state_with_transcript() -> None:
    """Tests LessonPipelineState extension supporting optional VideoTranscript.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    module = SyllabusModule(
        discipline_slug="estrategia",
        discipline_name="Estratégia",
        syllabus_summary="Resumo de estratégia.",
        topics=["Vantagem Competitiva"],
        bibliography=["Porter"],
    )
    transcript = VideoTranscript(
        source_filename="aula_01.mp4",
        discipline_slug="estrategia",
        duration_seconds=3600.0,
        model_name="large-v3",
        compute_type="int8_float16",
        processed_at=datetime.now(UTC),
        full_text_raw="Texto gravado da aula.",
        full_text_cleaned="Texto gravado da aula.",
        segments=[],
    )
    state = LessonPipelineState(
        discipline_slug="estrategia",
        discipline_name="Estratégia",
        lesson_number=1,
        lesson_title="Vantagem Competitiva",
        lesson_slug="vantagem-competitiva",
        source_slide_filename="slides.pdf",
        slides=[],
        syllabus=module,
        transcript=transcript,
    )
    assert state.transcript is not None
    assert state.transcript.source_filename == "aula_01.mp4"

    dumped = state.model_dump()
    restored = LessonPipelineState.model_validate(dumped)
    assert restored.transcript is not None
    assert restored.transcript.source_filename == "aula_01.mp4"


def test_wiki_lesson_output_with_transcript_filename() -> None:
    """Tests WikiLessonOutput extension supporting source_transcript_filename.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    output = WikiLessonOutput(
        discipline_slug="estrategia",
        discipline_name="Estratégia",
        lesson_number=1,
        lesson_title="Vantagem Competitiva",
        lesson_slug="vantagem-competitiva",
        processed_date=date(2026, 11, 7),
        source_slide_filename="slides.pdf",
        source_transcript_filename="aula_01.mp4",
        fact_check_passed=True,
        removed_unsupported_claims=0,
        body_markdown="Corpo da aula.",
        extracted_zettels=[],
    )
    assert output.source_transcript_filename == "aula_01.mp4"

    dumped = output.model_dump()
    restored = WikiLessonOutput.model_validate(dumped)
    assert restored.source_transcript_filename == "aula_01.mp4"
