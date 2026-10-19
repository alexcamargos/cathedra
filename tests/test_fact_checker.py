"""Unit tests for the factual auditing agent node (fact_checker.py).

Validates loading system prompts, formatting verification context, classifying claims
from S1 to S6, pruning unsupported (S4) statements, and updating LessonPipelineState.
"""

from pathlib import Path

import pytest

from mba_wiki.agents.fact_checker import (
    apply_audit_remediations,
    audit_lesson_draft,
    fact_check_node,
    format_fact_checker_user_prompt,
    get_fact_checker_prompt,
)
from mba_wiki.schemas import (
    AuditClaimsResponse,
    ClaimAuditItem,
    FactCheckResult,
    LessonPipelineState,
    SlideChunk,
    SyllabusModule,
)
from tests.conftest import FakeLLMClient


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
    assert "Brealey, Myers" in user_prompt
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
            raw_text="Aceitar VPL > 0.",
        )
    ]
    draft_text = (
        "O VPL é uma ferramenta confiável. "
        "A empresa XYZ obteve retorno de 900% garantido pelo governo em 1910."
    )

    verified_item = ClaimAuditItem(
        claim_id="claim-01",
        quote="O VPL é uma ferramenta confiável.",
        category="technical",
        verdict="verified",
    )
    unsupported_item = ClaimAuditItem(
        claim_id="claim-02",
        quote="A empresa XYZ obteve retorno de 900% garantido pelo governo em 1910.",
        category="metric",
        verdict="unsupported",
        severity="S4",
    )
    fake_llm_client.add_structured_response(
        AuditClaimsResponse(claims=[verified_item, unsupported_item])
    )

    result = audit_lesson_draft(
        draft_text=draft_text,
        slides=slides,
        syllabus=syllabus,
        client=fake_llm_client,
    )

    assert isinstance(result, FactCheckResult)
    assert len(result.audit_items) == 2
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
    slides = [SlideChunk(slide_number=1, title="VPL", raw_text="Regra VPL > 0")]
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

    claim_ok = ClaimAuditItem(
        claim_id="c1",
        quote="O VPL desconta fluxos à taxa de custo de capital.",
        category="technical",
        verdict="verified",
    )
    claim_dragons = ClaimAuditItem(
        claim_id="c2",
        quote="Segundo lendas medievais, dragões financiavam reis com taxas Selic negativas.",
        category="attribution",
        verdict="unsupported",
        severity="S4",
    )
    fake_llm_client.add_structured_response(AuditClaimsResponse(claims=[claim_ok, claim_dragons]))

    updated_state = fact_check_node(state=state, client=fake_llm_client)

    assert len(updated_state.audit_items) == 2
    assert updated_state.removed_unsupported_claims == 1
    assert updated_state.fact_check_passed is True
    assert updated_state.audited_markdown is not None
    assert "dragões" not in updated_state.audited_markdown
    assert "O VPL desconta fluxos" in updated_state.audited_markdown
