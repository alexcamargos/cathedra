"""Unit tests for Pydantic v2 data contracts.

Validates instantiation, serialization, defaults, and validation errors for all schemas
defined in Section 3 of SPEC.md.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from mba_wiki.schemas import (
    AtomicZettel,
    AuditClaimsResponse,
    ClaimAuditItem,
    DraftResult,
    FactCheckResult,
    HumanizerResult,
    LessonAuditReport,
    LessonPipelineState,
    SlideChunk,
    StructuredSyllabus,
    SyllabusModule,
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
