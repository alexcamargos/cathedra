"""Unit tests for the factual auditing agent node (fact_checker.py).

Validates loading system prompts, formatting verification context, classifying claims
from S1 to S6, pruning unsupported (S4) statements, and updating LessonPipelineState.
"""

from pathlib import Path

import pytest

from cathedra.agents.fact_checker import (
    apply_audit_remediations,
    audit_lesson_draft,
    fact_check_node,
    format_fact_checker_user_prompt,
    get_fact_checker_prompt,
)
from cathedra.schemas import (
    AtomicZettel,
    AuditClaimsResponse,
    ClaimAuditItem,
    DialecticalTension,
    FactCheckResult,
    GuardrailIssue,
    GuardrailResponse,
    LessonPipelineState,
    SlideChunk,
    SyllabusModule,
)
from tests.conftest import FakeLLMClient


@pytest.mark.parametrize(
    ("kind", "locator", "excerpt", "expected"),
    [
        ("slide", 1, "A taxa é 10%.", True),
        ("slide", 2, "A taxa é 10%.", False),
        ("slide", 1, "A taxa é 20%.", False),
        (None, None, None, False),
        ("syllabus", None, "Livro de Finanças", False),
    ],
)
def test_verified_claim_requires_located_material_evidence(
    kind: str | None,
    locator: int | None,
    excerpt: str | None,
    expected: bool,
) -> None:
    """An LLM verdict or an unconsulted book title alone cannot establish support."""
    from cathedra.agents.fact_checker import locate_evidence_source

    syllabus = SyllabusModule(
        discipline_slug="financas",
        discipline_name="Finanças",
        syllabus_summary="Investimento.",
        topics=["VPL"],
        bibliography=["Livro de Finanças"],
    )
    claim = ClaimAuditItem.model_validate(
        {
            "claim_id": "C1",
            "quote": "A taxa é 10%.",
            "category": "metric",
            "verdict": "verified",
            "evidence_source": "Livro de Finanças",
            "evidence_kind": kind,
            "evidence_locator": locator,
            "evidence_quote": excerpt,
            "evidence_status": "material_supported",
        }
    )
    source = locate_evidence_source(
        item=claim,
        slides=[SlideChunk(slide_number=1, title="Taxa", raw_text="A taxa é 10%.")],
        syllabus=syllabus,
        transcript=None,
    )
    assert source == ("Slide 1" if expected else None)


def test_transcript_evidence_identifies_segment_and_timestamps() -> None:
    """A matching transcript excerpt is traceable without implying independent confirmation."""
    from datetime import UTC, datetime

    from cathedra.agents.fact_checker import locate_evidence_source
    from cathedra.schemas import TranscriptSegment, VideoTranscript

    syllabus = SyllabusModule(
        discipline_slug="financas",
        discipline_name="Finanças",
        syllabus_summary="Investimento.",
        topics=[],
        bibliography=[],
    )
    segment = TranscriptSegment(
        id=7,
        start=12.0,
        end=16.0,
        text_raw="A taxa é 10%.",
        text_cleaned="A taxa é 10%.",
    )
    transcript = VideoTranscript(
        source_filename="aula.mp4",
        discipline_slug="financas",
        duration_seconds=20,
        model_name="teste",
        compute_type="int8",
        processed_at=datetime.now(UTC),
        full_text_raw=segment.text_raw,
        full_text_cleaned=segment.text_cleaned,
        segments=[segment],
    )
    claim = ClaimAuditItem.model_validate(
        {
            "claim_id": "C1",
            "quote": "A taxa é 10%.",
            "category": "metric",
            "verdict": "verified",
            "evidence_kind": "transcript",
            "evidence_locator": 7,
            "evidence_quote": "A taxa é 10%.",
        }
    )
    source = locate_evidence_source(
        item=claim,
        slides=[],
        syllabus=syllabus,
        transcript=transcript,
    )
    assert source == "Transcrição aula.mp4, segmento 7 (12.0s–16.0s)"
    prompt = format_fact_checker_user_prompt(
        draft_text="A taxa é 10%.",
        slides=[],
        syllabus=syllabus,
        transcript=transcript,
    )
    assert "[7] a taxa é 10%." in prompt.lower()


def test_get_fact_checker_prompt_loads_from_markdown() -> None:
    """Tests that the fact checker system prompt loads dynamically from its markdown file.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    prompt = get_fact_checker_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 50
    assert "S1" in prompt
    assert "S4" in prompt
    assert "unsupported" in prompt
    assert "proposed_fix" in prompt


def test_get_fact_checker_prompt_missing_file_raises(tmp_path: Path) -> None:
    """Tests that get_fact_checker_prompt raises FileNotFoundError when the file does not exist.

    Args:
        tmp_path: Pytest temporary directory fixture.

    Returns:
        None.

    Raises:
        None.
    """
    missing_path = tmp_path / "non_existent_fact_checker_prompt.md"
    with pytest.raises(FileNotFoundError, match="Fact checker system prompt file not found"):
        get_fact_checker_prompt(missing_path)


def test_format_fact_checker_user_prompt() -> None:
    """Tests that format_fact_checker_user_prompt creates comprehensive context.

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
        syllabus_summary="Decisões de investimento de longo prazo.",
        topics=["VPL", "WACC"],
        bibliography=["Brealey, Myers. Princípios de Finanças Corporativas."],
    )
    slides = [
        SlideChunk(
            slide_number=1,
            title="Valor Presente Líquido",
            raw_text="Aceitar se VPL > 0.",
            latex_equations=["\\text{VPL} > 0"],
        )
    ]
    draft_text = "O VPL é calculado descontando fluxos futuros."

    user_prompt = format_fact_checker_user_prompt(
        draft_text=draft_text,
        slides=slides,
        syllabus=syllabus,
    )

    assert "Finanças Corporativas" in user_prompt
    assert "Brealey, Myers" not in user_prompt
    assert "Bibliografia de Referência" not in user_prompt
    assert "Valor Presente Líquido" in user_prompt
    assert "Aceitar se VPL > 0." in user_prompt
    assert draft_text in user_prompt


def test_apply_audit_remediations_removes_unsupported_claim() -> None:
    """Tests that unsupported claims with severity S4 are pruned from the draft text.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    raw_text = (
        "O método do VPL considera o custo de oportunidade do capital. "
        "Em 1920, Isaac Newton inventou o cálculo do WACC durante seu exílio acadêmico. "
        "A aceitação de projetos com valor presente líquido positivo maximiza a riqueza."
    )
    unsupported_claim = ClaimAuditItem(
        claim_id="claim-001",
        quote="Em 1920, Isaac Newton inventou o cálculo do WACC durante seu exílio acadêmico.",
        category="attribution",
        verdict="unsupported",
        severity="S4",
        proposed_fix=None,
    )

    audited_text, removed_count, passed = apply_audit_remediations(
        raw_text=raw_text,
        audit_items=[unsupported_claim],
    )

    assert removed_count == 1
    assert passed is True
    assert "Isaac Newton" not in audited_text
    assert "O método do VPL considera o custo de oportunidade do capital." in audited_text
    assert "A aceitação de projetos com valor presente líquido positivo" in audited_text


def test_apply_audit_remediations_applies_proposed_fix() -> None:
    """Tests that false or imprecise claims (S1/S2) with proposed_fix are substituted.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    raw_text = "Na análise de investimentos, se o VPL for menor que zero o projeto deve ser aceito."
    false_claim = ClaimAuditItem(
        claim_id="claim-002",
        quote="se o VPL for menor que zero o projeto deve ser aceito",
        category="technical",
        verdict="false",
        severity="S1",
        proposed_fix="se o VPL for maior que zero o projeto deve ser aceito",
        evidence_source="Slide 2: Regra de Decisão do VPL",
    )

    audited_text, removed_count, passed = apply_audit_remediations(
        raw_text=raw_text,
        audit_items=[false_claim],
    )

    assert removed_count == 0
    assert passed is True
    assert "se o VPL for maior que zero o projeto deve ser aceito" in audited_text
    assert "menor que zero" not in audited_text


def test_apply_audit_remediations_unresolved_blocker_fails() -> None:
    """Tests that unresolvable critical claims (S1/S3/S5 without fix) cause audit failure.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    raw_text = "Afirmação que distorce totalmente a teoria de Modigliani-Miller."
    blocker_claim = ClaimAuditItem(
        claim_id="claim-003",
        quote="Afirmação que distorce totalmente a teoria de Modigliani-Miller.",
        category="technical",
        verdict="misleading",
        severity="S3",
        proposed_fix=None,
    )

    _audited_text, removed_count, passed = apply_audit_remediations(
        raw_text=raw_text,
        audit_items=[blocker_claim],
    )

    assert removed_count == 0
    assert passed is False


def test_audit_lesson_draft_with_fake_llm(fake_llm_client: FakeLLMClient) -> None:
    """Tests complete audit workflow producing FactCheckResult via FakeLLMClient.

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
        syllabus_summary="Gestão financeira e criação de valor.",
        topics=["VPL", "TIR"],
        bibliography=["Brealey & Myers"],
    )
    slides = [
        SlideChunk(
            slide_number=1,
            title="Avaliação de Investimento",
            raw_text="Aceitar VPL > 0. O VPL é uma ferramenta confiável.",
        )
    ]
    draft_text = (
        "O VPL é uma ferramenta confiável. "
        "A empresa XYZ obteve retorno de 900% garantido pelo governo em 1910."
    )

    unsupported_issue = GuardrailIssue(
        claim_id="claim-02",
        quote="A empresa XYZ obteve retorno de 900% garantido pelo governo em 1910.",
        category="metric",
        verdict="unsupported",
        severity="S4",
        reason="Exemplo empírico inventado ausente dos slides e da aula.",
    )
    fake_llm_client.add_structured_response(GuardrailResponse(issues=[unsupported_issue]))

    result = audit_lesson_draft(
        draft_text=draft_text,
        slides=slides,
        syllabus=syllabus,
        client=fake_llm_client,
    )

    assert isinstance(result, FactCheckResult)
    assert fake_llm_client.last_call is not None
    assert fake_llm_client.last_call.response_model is GuardrailResponse
    assert len(result.audit_items) == 1
    assert result.removed_unsupported_claims == 1
    assert result.fact_check_passed is True
    assert "XYZ" not in result.audited_markdown
    assert "O VPL é uma ferramenta confiável." in result.audited_markdown


def test_fact_check_node_updates_pipeline_state(fake_llm_client: FakeLLMClient) -> None:
    """Tests that fact_check_node updates LessonPipelineState fields correctly.

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
        syllabus_summary="Finanças corporativas.",
        topics=["VPL"],
        bibliography=["Brealey"],
    )
    slides = [
        SlideChunk(
            slide_number=1,
            title="VPL",
            raw_text="O VPL desconta fluxos à taxa de custo de capital.",
        )
    ]
    raw_draft = (
        "O VPL desconta fluxos à taxa de custo de capital. "
        "Segundo lendas medievais, dragões financiavam reis com taxas Selic negativas."
    )

    state = LessonPipelineState(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        lesson_number=1,
        lesson_title="Critérios de Avaliação",
        lesson_slug="criterios-avaliacao",
        source_slide_filename="aula1.pdf",
        slides=slides,
        syllabus=syllabus,
        raw_draft=raw_draft,
    )

    issue_dragons = GuardrailIssue(
        claim_id="c2",
        quote="Segundo lendas medievais, dragões financiavam reis com taxas Selic negativas.",
        category="attribution",
        verdict="unsupported",
        severity="S4",
        reason="Alucinação evidente sem base na aula.",
    )
    fake_llm_client.add_structured_response(GuardrailResponse(issues=[issue_dragons]))

    updated_state = fact_check_node(state=state, client=fake_llm_client)

    assert len(updated_state.audit_items) == 1
    assert updated_state.removed_unsupported_claims == 1
    assert updated_state.fact_check_passed is True
    assert updated_state.audited_markdown is not None
    assert "dragões" not in updated_state.audited_markdown
    assert "O VPL desconta fluxos" in updated_state.audited_markdown


def test_apply_audit_remediations_resilient_whitespace() -> None:
    """Tests that quote matching handles whitespace differences and newlines gracefully.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    raw_text = (
        "O método do VPL analisa fluxos de caixa.\n"
        "Em 1920, Isaac Newton inventou o cálculo\n"
        "do WACC durante seu exílio acadêmico.\n"
        "A tomada de decisão considera o custo de capital."
    )
    # The LLM quote has single spaces where raw_text had newlines
    unsupported_claim = ClaimAuditItem(
        claim_id="claim-ws",
        quote="Em 1920, Isaac Newton inventou o cálculo do WACC durante seu exílio acadêmico.",
        category="attribution",
        verdict="unsupported",
        severity="S4",
    )

    audited_text, removed_count, passed = apply_audit_remediations(
        raw_text=raw_text,
        audit_items=[unsupported_claim],
    )

    assert removed_count == 1
    assert passed is True
    assert "Isaac Newton" not in audited_text
    assert "O método do VPL analisa fluxos de caixa." in audited_text


def test_apply_audit_remediations_false_without_fix_triggers_blocker() -> None:
    """Tests that any false verdict without proposed_fix causes audit to fail.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    raw_text = "O VPL negativo indica que o projeto deve ser aprovado imediatamente."
    false_unfixed_claim = ClaimAuditItem(
        claim_id="claim-false",
        quote="O VPL negativo indica que o projeto deve ser aprovado imediatamente.",
        category="technical",
        verdict="false",
        severity="S2",  # Severity is S2, but verdict is false without proposed_fix
        proposed_fix=None,
    )

    _audited_text, removed_count, passed = apply_audit_remediations(
        raw_text=raw_text,
        audit_items=[false_unfixed_claim],
    )

    assert passed is False


def test_apply_audit_remediations_unsupported_s4_not_found_triggers_blocker() -> None:
    """Tests that an unsupported S4 claim whose quote cannot be found triggers a blocker.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    raw_text = "O fluxo de caixa livre da firma é descontado pelo custo médio ponderado."
    unmatched_s4 = ClaimAuditItem(
        claim_id="claim-ghost-s4",
        quote="Frase inexistente sobre dragões e alquimia financeira que não está no texto.",
        category="technical",
        verdict="unsupported",
        severity="S4",
        proposed_fix=None,
    )

    _audited_text, removed_count, passed = apply_audit_remediations(
        raw_text=raw_text,
        audit_items=[unmatched_s4],
    )

    assert removed_count == 0
    assert passed is False


def test_apply_audit_remediations_imprecise_s2_not_found_triggers_blocker() -> None:
    """Tests that an imprecise S2 claim whose fix cannot be applied triggers a blocker.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    raw_text = "O CAPM estima o retorno esperado com base no beta do ativo."
    unmatched_s2 = ClaimAuditItem(
        claim_id="claim-ghost-s2",
        quote="Taxa Selic era de 45% ao mês em 2024.",
        category="metric",
        verdict="imprecise",
        severity="S2",
        proposed_fix="Taxa Selic média foi de 10,5% ao ano em 2024.",
    )

    _audited_text, removed_count, passed = apply_audit_remediations(
        raw_text=raw_text,
        audit_items=[unmatched_s2],
    )

    assert removed_count == 0
    assert passed is False


def test_apply_audit_remediations_punctuation_tolerant_matching_s4() -> None:
    """Tests that S4 claims with minor punctuation/quote differences are successfully pruned.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    raw_text = (
        "A análise de sensibilidade testa múltiplos cenários. "
        'Segundo o livro "Finanças Mágicas", o ROI é sempre infinito! '
        "O custo de capital próprio deve refletir o risco sistemático."
    )
    # The quote omits the exclamation mark and uses different quotes
    tolerant_s4 = ClaimAuditItem(
        claim_id="claim-tolerant-s4",
        quote="Segundo o livro “Finanças Mágicas”, o ROI é sempre infinito",
        category="attribution",
        verdict="unsupported",
        severity="S4",
        proposed_fix=None,
    )

    audited_text, removed_count, passed = apply_audit_remediations(
        raw_text=raw_text,
        audit_items=[tolerant_s4],
    )

    assert removed_count == 1
    assert passed is True
    assert "Finanças Mágicas" not in audited_text
    assert "A análise de sensibilidade testa múltiplos cenários." in audited_text


def test_apply_audit_remediations_punctuation_tolerant_matching_proposed_fix() -> None:
    """Tests that imprecise S2 claims with punctuation differences get fixed correctly.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    raw_text = "A margem EBITDA da empresa no período fiscal foi de 32,5%."
    # The LLM quote omitted the trailing dot
    imprecise_claim = ClaimAuditItem(
        claim_id="claim-tolerant-s2",
        quote="A margem EBITDA da empresa no período fiscal foi de 32,5%",
        category="metric",
        verdict="imprecise",
        severity="S2",
        proposed_fix="A margem EBITDA da empresa no período fiscal foi de 28,4%",
    )

    audited_text, removed_count, passed = apply_audit_remediations(
        raw_text=raw_text,
        audit_items=[imprecise_claim],
    )

    assert passed is True
    assert "28,4%" in audited_text
    assert "32,5%" not in audited_text


def test_format_fact_checker_user_prompt_includes_zettels_and_tensions() -> None:
    """Tests that format_fact_checker_user_prompt includes candidate zettels and tensions.

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
        syllabus_summary="Resumo da disciplina.",
        topics=["VPL"],
        bibliography=["Brealey"],
    )
    slides = [SlideChunk(slide_number=1, title="VPL", raw_text="Regra VPL")]
    zettel = AtomicZettel(
        slug="vpl-conceito",
        title="Conceito de VPL",
        domain_tags=["financas"],
        content_markdown="O VPL mede a agregação de valor.",
        related_links=[],
    )

    tension = DialecticalTension(
        slug="eficiencia-vs-resiliencia",
        title="Eficiência vs Resiliência",
        pole_a_discipline="financas-corporativas",
        pole_a_framework="WACC",
        pole_a_thesis="Minimizar custo de capital",
        pole_b_discipline="operacoes",
        pole_b_framework="Just in Time",
        pole_b_thesis="Otimizar estoque zero",
        tension_nature="Curto vs Longo Prazo",
        synthesis_guidelines="Manter colchão de liquidez operacional",
        related_zettel_slugs=["vpl-conceito"],
    )

    prompt = format_fact_checker_user_prompt(
        draft_text="Texto da aula sobre critérios de decisão.",
        slides=slides,
        syllabus=syllabus,
        zettels=[zettel],
        tensions=[tension],
    )

    assert "## Fonte 1: Escopo Curricular da Disciplina" in prompt
    assert "Brealey" not in prompt
    assert "## Fonte 2: Conteúdo Literal dos Slides da Aula" in prompt
    assert "## Rascunho da Aula a ser Auditado" in prompt
    assert "## Conceitos Atômicos (Zettels) a serem Auditados" in prompt
    assert "[Zettel: vpl-conceito] Conceito de VPL" in prompt
    assert "## Tensões Dialéticas a serem Auditadas" in prompt
    assert "[Tensão: eficiencia-vs-resiliencia] Eficiência vs Resiliência" in prompt


def test_fact_check_node_purges_unsupported_zettels_and_tensions(
    fake_llm_client: FakeLLMClient,
) -> None:
    """Tests that fact_check_node purges zettels and tensions with unresolvable S1/S4 errors.

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
        syllabus_summary="Finanças corporativas.",
        topics=["VPL"],
        bibliography=["Brealey"],
    )
    slides = [
        SlideChunk(
            slide_number=1,
            title="VPL",
            raw_text="O VPL desconta fluxos à taxa de custo de capital.",
        )
    ]

    valid_zettel = AtomicZettel(
        slug="vpl-valido",
        title="VPL Válido",
        domain_tags=["financas"],
        content_markdown="O VPL desconta fluxos à taxa de custo de capital.",
        related_links=[],
    )
    hallucinated_zettel = AtomicZettel(
        slug="alquimia-financeira",
        title="Alquimia de Newton",
        domain_tags=["misticismo"],
        content_markdown="Isaac Newton descobriu a fórmula do WACC através de alquimia medieval.",
        related_links=[],
    )
    hallucinated_tension = DialecticalTension(
        slug="alquimia-vs-wacc",
        title="Alquimia vs WACC",
        pole_a_discipline="financas-corporativas",
        pole_a_framework="WACC",
        pole_a_thesis="Tese A",
        pole_b_discipline="historia",
        pole_b_framework="Alquimia Hermética",
        pole_b_thesis="Tese B inventada",
        tension_nature="Racional vs Místico",
        synthesis_guidelines="Diretriz",
        related_zettel_slugs=[],
    )

    state = LessonPipelineState(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        lesson_number=1,
        lesson_title="Critérios de Avaliação",
        lesson_slug="criterios-avaliacao",
        source_slide_filename="aula_01.pdf",
        slides=slides,
        syllabus=syllabus,
        raw_draft="O VPL desconta fluxos à taxa de custo de capital.",
        extracted_zettels=[valid_zettel, hallucinated_zettel],
        detected_tensions=[hallucinated_tension],
    )

    # Auditor flags hallucinated zettel and hallucinated tension as unsupported (S4)
    issue_zettel = GuardrailIssue(
        claim_id="claim-zettel-s4",
        quote="Isaac Newton descobriu a fórmula do WACC através de alquimia medieval",
        category="attribution",
        verdict="unsupported",
        severity="S4",
    )
    issue_tension = GuardrailIssue(
        claim_id="claim-tension-s4",
        quote="Alquimia Hermética",
        category="technical",
        verdict="unsupported",
        severity="S4",
    )

    fake_llm_client.add_structured_response(GuardrailResponse(issues=[issue_zettel, issue_tension]))

    updated_state = fact_check_node(state=state, client=fake_llm_client)

    # Valid zettel is preserved
    assert len(updated_state.extracted_zettels) == 1
    assert updated_state.extracted_zettels[0].slug == "vpl-valido"
    # Hallucinated zettel and tension are purged
    assert not any(z.slug == "alquimia-financeira" for z in updated_state.extracted_zettels)
    assert len(updated_state.detected_tensions) == 0
    # Audit items recorded
    assert len(updated_state.audit_items) == 2
    assert updated_state.removed_unsupported_claims >= 2
    assert updated_state.fact_check_passed is True


def test_format_fact_checker_user_prompt_with_transcript() -> None:
    """Tests that format_fact_checker_user_prompt includes speech transcript as Source 3.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    from datetime import UTC, datetime

    from cathedra.schemas import VideoTranscript

    syllabus = SyllabusModule(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        syllabus_summary="Decisões de investimento.",
        topics=["VPL"],
        bibliography=["Brealey, Myers"],
    )
    slides = [SlideChunk(slide_number=1, title="VPL", raw_text="VPL > 0")]
    transcript = VideoTranscript(
        source_filename="aula_vpl.mp4",
        discipline_slug="financas-corporativas",
        duration_seconds=3600.0,
        model_name="large-v3",
        compute_type="int8_float16",
        processed_at=datetime.now(UTC),
        full_text_raw=(
            "O professor disse em aula que a taxa de desconto reflete o custo de oportunidade."
        ),
        full_text_cleaned=(
            "A taxa de desconto reflete o custo de oportunidade do capital investido."
        ),
        segments=[],
    )

    prompt = format_fact_checker_user_prompt(
        draft_text="A taxa de desconto reflete o custo de oportunidade.",
        slides=slides,
        syllabus=syllabus,
        transcript=transcript,
    )
    assert "Fonte 3: Transcrição da Fala do Professor na Videoaula" in prompt
    assert "A taxa de desconto reflete o custo de oportunidade do capital investido." in prompt


def test_fact_check_node_transmits_state_transcript(fake_llm_client: FakeLLMClient) -> None:
    """Tests that fact_check_node transmits state.transcript to LLM user prompt when present.

    Args:
        fake_llm_client: Mock LLM client fixture.

    Returns:
        None.

    Raises:
        None.
    """
    from datetime import UTC, datetime

    from cathedra.schemas import VideoTranscript

    syllabus = SyllabusModule(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        syllabus_summary="Decisões de investimento.",
        topics=["VPL"],
        bibliography=["Brealey, Myers"],
    )
    slides = [SlideChunk(slide_number=1, title="VPL", raw_text="VPL > 0")]
    transcript = VideoTranscript(
        source_filename="aula_vpl.mp4",
        discipline_slug="financas-corporativas",
        duration_seconds=3600.0,
        model_name="large-v3",
        compute_type="int8_float16",
        processed_at=datetime.now(UTC),
        full_text_raw="Fala gravada.",
        full_text_cleaned="O professor mencionou o caso real da fusão Ambev em 1999.",
        segments=[],
    )
    state = LessonPipelineState(
        discipline_slug="financas-corporativas",
        discipline_name="Finanças Corporativas",
        lesson_number=1,
        lesson_title="Critérios",
        lesson_slug="criterios",
        source_slide_filename="aula.pdf",
        slides=slides,
        syllabus=syllabus,
        raw_draft="Na aula foi discutido o caso real da fusão Ambev em 1999.",
        transcript=transcript,
    )

    fake_llm_client.add_structured_response(GuardrailResponse(issues=[]))

    fact_check_node(state=state, client=fake_llm_client)

    assert fake_llm_client.last_call is not None
    user_prompt = fake_llm_client.last_call.user_prompt
    assert "Fonte 3: Transcrição da Fala do Professor na Videoaula" in user_prompt
    assert "O professor mencionou o caso real da fusão Ambev em 1999." in user_prompt


def test_locate_evidence_source_strips_stray_markdown_backticks_and_quotes() -> None:
    """Matches slide evidence even when evidence_quote has stray outer backticks."""
    from cathedra.agents.fact_checker import locate_evidence_source

    syllabus = SyllabusModule(
        discipline_slug="estatistica",
        discipline_name="Estatística",
        syllabus_summary="Resumo.",
        topics=["Medidas de Forma"],
        bibliography=[],
    )
    slides = [
        SlideChunk(
            slide_number=24,
            title="Medidas de Forma",
            raw_text="Fonte: Fávero e Belfiore (2024, Cap. 2)",
        )
    ]
    item = ClaimAuditItem(
        claim_id="C18",
        quote="Medidas de Forma.",
        category="attribution",
        verdict="verified",
        evidence_kind="slide",
        evidence_locator=24,
        evidence_quote="Fonte: Fávero e Belfiore (2024, Cap. 2)`",
    )

    assert locate_evidence_source(item, slides, syllabus, None) == "Slide 24"


def test_locate_evidence_source_rejects_empty_after_stripping_or_missing_quote() -> None:
    """Returns None when evidence_quote is only punctuation/backticks or absent from source."""
    from cathedra.agents.fact_checker import locate_evidence_source

    syllabus = SyllabusModule(
        discipline_slug="estatistica",
        discipline_name="Estatística",
        syllabus_summary="Resumo.",
        topics=["Medidas de Forma"],
        bibliography=[],
    )
    slides = [SlideChunk(slide_number=1, title="Intro", raw_text="Texto real do slide.")]

    empty_item = ClaimAuditItem(
        claim_id="C1",
        quote="Algo.",
        category="technical",
        verdict="verified",
        evidence_kind="slide",
        evidence_locator=1,
        evidence_quote="``",
    )
    missing_item = ClaimAuditItem(
        claim_id="C2",
        quote="Algo.",
        category="technical",
        verdict="verified",
        evidence_kind="slide",
        evidence_locator=1,
        evidence_quote="`Trecho inventado`",
    )

    assert locate_evidence_source(empty_item, slides, syllabus, None) is None
    assert locate_evidence_source(missing_item, slides, syllabus, None) is None


def test_format_fact_checker_user_prompt_compacts_segments_without_duplication() -> None:
    """Sends compact [Segmento id] text_cleaned lines without duplicating raw or full text."""
    from datetime import UTC, datetime

    from cathedra.schemas import TranscriptSegment, VideoTranscript

    syllabus = SyllabusModule(
        discipline_slug="estatistica",
        discipline_name="Estatística",
        syllabus_summary="Resumo.",
        topics=["Amostragem"],
        bibliography=[],
    )
    slides = [SlideChunk(slide_number=1, title="Intro", raw_text="Amostragem aleatória.")]
    transcript = VideoTranscript(
        source_filename="aula01.mp4",
        discipline_slug="estatistica",
        duration_seconds=120.0,
        model_name="large-v3",
        compute_type="int8_float16",
        processed_at=datetime(2026, 11, 9, 2, 0, tzinfo=UTC),
        full_text_raw="texto bruto completo unico",
        full_text_cleaned="texto limpo completo unico",
        segments=[
            TranscriptSegment(
                id=1,
                start=0.0,
                end=5.0,
                text_raw="ah texto bruto segmento",
                text_cleaned="texto limpo segmento",
            )
        ],
    )

    prompt = format_fact_checker_user_prompt(
        draft_text="Rascunho.",
        slides=slides,
        syllabus=syllabus,
        transcript=transcript,
    )

    assert "[1] texto limpo segmento" in prompt
    assert "texto bruto segmento" not in prompt
    assert "texto limpo completo unico" not in prompt


def test_audit_lesson_draft_runs_single_pass_without_hidden_repair_loop(
    fake_llm_client: FakeLLMClient,
) -> None:
    """Guardrail executes strictly in a single LLM pass without a hidden repair loop."""
    syllabus = SyllabusModule(
        discipline_slug="estatistica",
        discipline_name="Estatística",
        syllabus_summary="Resumo.",
        topics=["Média"],
        bibliography=[],
    )
    slides = [SlideChunk(slide_number=1, title="Média", raw_text="A média é a soma sobre n.")]

    fake_llm_client.add_structured_response(
        GuardrailResponse(
            issues=[
                GuardrailIssue(
                    claim_id="C01",
                    quote="Frase parafraseada que não casa.",
                    category="technical",
                    verdict="unsupported",
                    severity="S4",
                    reason="Alucinação não localizada literalmente.",
                )
            ]
        )
    )

    result = audit_lesson_draft(
        draft_text="A média é a soma sobre n.",
        slides=slides,
        syllabus=syllabus,
        client=fake_llm_client,
    )

    assert result.fact_check_passed is False
    assert len(fake_llm_client.calls) == 1
    assert fake_llm_client.calls[0].response_model is GuardrailResponse


def test_apply_audit_remediations_treats_s6_as_non_blocking() -> None:
    """Minor stylistic note S6 without fix does not block publication."""
    items = [
        ClaimAuditItem(
            claim_id="C01",
            quote="Texto principal.",
            category="technical",
            verdict="imprecise",
            severity="S6",
        )
    ]
    cleaned, removed, passed = apply_audit_remediations("Texto principal.", items)
    assert passed is True
    assert removed == 0
    assert cleaned == "Texto principal."


def test_audit_humanized_invariance_blocks_distortion(
    fake_llm_client: FakeLLMClient,
) -> None:
    """Invariance check passes when clean and blocks when humanizer introduces S1 distortion."""
    from cathedra.agents.fact_checker import audit_humanized_invariance

    fake_llm_client.add_structured_response(AuditClaimsResponse(claims=[]))
    ok = audit_humanized_invariance(
        audited_markdown="O limite é 5%.",
        humanized_markdown="Adota-se o limite de 5%.",
        client=fake_llm_client,
    )
    assert ok.fact_check_passed is True

    fake_llm_client.add_structured_response(
        AuditClaimsResponse(
            claims=[
                ClaimAuditItem(
                    claim_id="INV-1",
                    quote="Adota-se o limite de 10%.",
                    category="metric",
                    verdict="false",
                    severity="S1",
                )
            ]
        )
    )
    blocked = audit_humanized_invariance(
        audited_markdown="O limite é 5%.",
        humanized_markdown="Adota-se o limite de 10%.",
        client=fake_llm_client,
    )
    assert blocked.fact_check_passed is False


def test_audit_lesson_draft_does_not_mutate_input_zettels_in_place(
    fake_llm_client: FakeLLMClient,
) -> None:
    """Guardrail remediation operates on defensive copies without mutating caller zettels."""
    syllabus = SyllabusModule(
        discipline_slug="estatistica",
        discipline_name="Estatística",
        syllabus_summary="Resumo.",
        topics=["Variância"],
        bibliography=[],
    )
    slides = [SlideChunk(slide_number=1, title="Variância", raw_text="Divide por n - 1.")]
    original_zettel = AtomicZettel(
        slug="variancia-amostral",
        title="Variância Amostral",
        domain_tags=["estatistica"],
        content_markdown="A variância amostral divide por n + 1.",
        related_links=[],
    )

    fake_llm_client.add_structured_response(
        GuardrailResponse(
            issues=[
                GuardrailIssue(
                    claim_id="C01",
                    quote="A variância amostral divide por n + 1.",
                    category="formula",
                    verdict="false",
                    severity="S1",
                    proposed_fix="A variância amostral divide por n - 1.",
                )
            ]
        )
    )

    result = audit_lesson_draft(
        draft_text="Texto limpo da aula.",
        slides=slides,
        syllabus=syllabus,
        client=fake_llm_client,
        zettels=[original_zettel],
    )

    assert result.fact_check_passed is True
    assert result.validated_zettels[0].content_markdown == "A variância amostral divide por n - 1."
    assert original_zettel.content_markdown == "A variância amostral divide por n + 1."


def test_audit_lesson_draft_allows_imprecise_s2_without_fix_as_non_blocking(
    fake_llm_client: FakeLLMClient,
) -> None:
    """An S2 imprecise observation without a proposed_fix does not hard-block the lesson."""
    syllabus = SyllabusModule(
        discipline_slug="estatistica",
        discipline_name="Estatística",
        syllabus_summary="Resumo.",
        topics=["Desvio Padrão"],
        bibliography=[],
    )
    slides = [SlideChunk(slide_number=1, title="Dispersão", raw_text="S = raiz da variância.")]
    draft = (
        "É a raiz quadrada da variância, retornando à unidade original da variável "
        "e facilitando a interpretação gerencial."
    )

    fake_llm_client.add_structured_response(
        GuardrailResponse(
            issues=[
                GuardrailIssue(
                    claim_id="C33",
                    quote=draft,
                    category="technical",
                    verdict="imprecise",
                    severity="S2",
                    reason="Observação didática sem correção sugerida.",
                    proposed_fix=None,
                )
            ]
        )
    )

    result = audit_lesson_draft(
        draft_text=draft,
        slides=slides,
        syllabus=syllabus,
        client=fake_llm_client,
    )

    assert result.fact_check_passed is True
    assert len(result.audit_items) == 1


def test_audit_lesson_draft_allow_pending_review_passes_non_critical(
    fake_llm_client: FakeLLMClient,
) -> None:
    """With allow_pending_review=True, non-critical orphan S4 items pass with pending flag."""
    syllabus = SyllabusModule(
        discipline_slug="estatistica",
        discipline_name="Estatística",
        syllabus_summary="Resumo.",
        topics=["Média"],
        bibliography=[],
    )
    slides = [SlideChunk(slide_number=1, title="Média", raw_text="A média é a soma sobre n.")]

    fake_llm_client.add_structured_response(
        GuardrailResponse(
            issues=[
                GuardrailIssue(
                    claim_id="C01",
                    quote="Trecho não localizado para remoção.",
                    category="technical",
                    verdict="unsupported",
                    severity="S4",
                )
            ]
        )
    )

    result = audit_lesson_draft(
        draft_text="A média é a soma sobre n.",
        slides=slides,
        syllabus=syllabus,
        client=fake_llm_client,
        allow_pending_review=True,
    )

    assert result.fact_check_passed is True
    assert result.has_pending_review is True


def test_audit_lesson_draft_allow_pending_review_still_blocks_s1(
    fake_llm_client: FakeLLMClient,
) -> None:
    """Critical S1/false errors without fix still block even with allow_pending_review=True."""
    syllabus = SyllabusModule(
        discipline_slug="estatistica",
        discipline_name="Estatística",
        syllabus_summary="Resumo.",
        topics=["Média"],
        bibliography=[],
    )
    slides = [SlideChunk(slide_number=1, title="Média", raw_text="A média é a soma sobre n.")]

    fake_llm_client.add_structured_response(
        GuardrailResponse(
            issues=[
                GuardrailIssue(
                    claim_id="C01",
                    quote="A média é sempre zero.",
                    category="technical",
                    verdict="false",
                    severity="S1",
                )
            ]
        )
    )

    result = audit_lesson_draft(
        draft_text="A média é sempre zero.",
        slides=slides,
        syllabus=syllabus,
        client=fake_llm_client,
        allow_pending_review=True,
    )

    assert result.fact_check_passed is False
    assert result.has_pending_review is False


def test_audit_lesson_draft_allow_pending_review_blocks_orphan_s1_and_s5(
    fake_llm_client: FakeLLMClient,
) -> None:
    """Orphan S1/S5 critical errors block even with allow_pending_review=True."""
    syllabus = SyllabusModule(
        discipline_slug="estatistica",
        discipline_name="Estatística",
        syllabus_summary="Resumo.",
        topics=["Média"],
        bibliography=[],
    )
    slides = [SlideChunk(slide_number=1, title="Média", raw_text="A média é a soma sobre n.")]

    fake_llm_client.add_structured_response(
        GuardrailResponse(
            issues=[
                GuardrailIssue(
                    claim_id="C-ORPHAN",
                    quote="Trecho crítico S1 parafraseado que não casa literalmente.",
                    category="formula",
                    verdict="false",
                    severity="S1",
                    reason="Fórmula invertida no rascunho.",
                )
            ]
        )
    )

    result = audit_lesson_draft(
        draft_text="A média é a soma sobre n.",
        slides=slides,
        syllabus=syllabus,
        client=fake_llm_client,
        allow_pending_review=True,
    )

    assert result.fact_check_passed is False
    assert result.has_pending_review is False


def test_apply_audit_remediations_preserves_code_block_and_nested_list_indentation() -> None:
    """Tests that post-remediation cleanup preserves fenced code and nested list indentation.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    raw_text = (
        "Introdução válida. Frase inventada sem lastro.\n\n"
        "```python\n"
        "def media(valores):\n"
        "    if not valores:\n"
        "        return 0.0\n"
        "    return sum(valores) / len(valores)\n"
        "```\n\n"
        "- Item principal\n"
        "  - Subitem aninhado\n"
    )
    claim = ClaimAuditItem(
        claim_id="C1",
        quote="Frase inventada sem lastro.",
        category="technical",
        verdict="unsupported",
        severity="S4",
    )
    cleaned, removed, passed = apply_audit_remediations(raw_text, [claim])
    assert passed is True
    assert removed == 1
    assert "Frase inventada" not in cleaned
    assert "Introdução válida.\n\n```python\n" in cleaned
    assert "    if not valores:\n        return 0.0\n" in cleaned
    assert "  - Subitem aninhado" in cleaned
