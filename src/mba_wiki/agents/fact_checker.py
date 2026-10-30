"""Factual auditing agent node for verifying lesson drafts against source materials.

Extracts objective claims, cross-references statements against presentation slides
and course syllabus guidelines, classifies discrepancies from S1 to S6, prunes
unsupported (S4) claims, applies factual fixes, and updates pipeline state.
"""

import re
from pathlib import Path

from mba_wiki.agents.llm_client import StructuredLLMClient
from mba_wiki.schemas import (
    AuditClaimsResponse,
    ClaimAuditItem,
    FactCheckResult,
    LessonPipelineState,
    SlideChunk,
    SyllabusModule,
)

DEFAULT_FACT_CHECKER_PROMPT_PATH = Path(__file__).parent / "prompts" / "fact_checker.md"


def get_fact_checker_prompt(prompt_path: Path | None = None) -> str:
    """Loads the fact checker system prompt dynamically from an external markdown file.

    Args:
        prompt_path: Optional explicit path to prompt file.
            Defaults to DEFAULT_FACT_CHECKER_PROMPT_PATH.

    Returns:
        String content of the fact checker prompt markdown file.

    Raises:
        FileNotFoundError: If the specified prompt file cannot be found on disk.
    """
    resolved_path = prompt_path or DEFAULT_FACT_CHECKER_PROMPT_PATH
    if not resolved_path.is_file():
        raise FileNotFoundError(f"Fact checker system prompt file not found: {resolved_path}")
    return resolved_path.read_text(encoding="utf-8")


def format_fact_checker_user_prompt(
    draft_text: str,
    slides: list[SlideChunk],
    syllabus: SyllabusModule,
) -> str:
    """Formats contextual input payload containing draft prose and source materials.

    Args:
        draft_text: Preliminary lesson draft prose to audit.
        slides: Primary source slide chunks containing text, tables, and LaTeX equations.
        syllabus: Anchoring syllabus module with official scope and bibliography.

    Returns:
        Formatted markdown string representing the prompt for the fact checker LLM.

    Raises:
        None.
    """
    sections: list[str] = []

    # 1. Official Course Guidelines
    bib_list = "\n".join(f"- {b}" for b in syllabus.bibliography)
    topics_list = "\n".join(f"- {t}" for t in syllabus.topics)
    syllabus_sec = (
        f"## Fonte 1: Ementa e Bibliografia Oficial da Disciplina\n"
        f"Disciplina: {syllabus.discipline_name} (slug: `{syllabus.discipline_slug}`)\n\n"
        f"### Resumo da Ementa\n{syllabus.syllabus_summary}\n\n"
        f"### Tópicos Curriculares\n{topics_list}\n\n"
        f"### Bibliografia de Referência\n{bib_list}"
    )
    sections.append(syllabus_sec)

    # 2. Slide Source Content
    slides_parts: list[str] = ["## Fonte 2: Conteúdo Literal dos Slides da Aula"]
    for chunk in slides:
        header = f"### Slide {chunk.slide_number}: {chunk.title}"
        body = chunk.raw_text.strip()
        eqs = ""
        if chunk.latex_equations:
            eqs = "\nEquações:\n" + "\n".join(f"- $${e}$$" for e in chunk.latex_equations)
        slides_parts.append(f"{header}\n{body}{eqs}")
    sections.append("\n\n".join(slides_parts))

    # 3. Draft Text to Audit
    draft_sec = f"## Rascunho da Aula a ser Auditado\n\n```markdown\n{draft_text}\n```"
    sections.append(draft_sec)

    return "\n\n".join(sections)


def apply_audit_remediations(
    raw_text: str,
    audit_items: list[ClaimAuditItem],
) -> tuple[str, int, bool]:
    """Applies factual corrections and prunes unsupported claims from draft text.

    For unsupported claims (S4), removes the quote from the text and tracks count.
    For false or imprecise claims (S1, S2) with proposed_fix, replaces quote with fix.
    Determines whether the text passed factual verification without blocking issues.

    Args:
        raw_text: Original preliminary draft text.
        audit_items: List of ClaimAuditItem instances with verdicts and severities.

    Returns:
        Tuple containing (audited_markdown, removed_unsupported_claims, fact_check_passed).

    Raises:
        None.
    """
    audited_text = raw_text
    removed_count = 0
    has_unresolved_blockers = False

    for item in audit_items:
        # Build flexible regex for quote to handle whitespace and newline differences
        quote_words = [re.escape(w) for w in item.quote.split()]
        flex_pattern = re.compile(r"\s+".join(quote_words)) if quote_words else None

        # Check for unsupported claims (S4)
        if item.verdict == "unsupported" or item.severity == "S4":
            if item.quote in audited_text:
                pattern = re.escape(item.quote)
                audited_text = re.sub(rf"\s*{pattern}\s*", " ", audited_text)
                removed_count += 1
            elif flex_pattern and flex_pattern.search(audited_text):
                audited_text = flex_pattern.sub(" ", audited_text)
                removed_count += 1
            continue

        # Check for false, imprecise, or misleading claims
        if item.verdict in ("false", "imprecise", "misleading") or item.severity in (
            "S1",
            "S2",
            "S3",
            "S5",
        ):
            if item.proposed_fix:
                if item.quote in audited_text:
                    audited_text = audited_text.replace(item.quote, item.proposed_fix)
                elif flex_pattern and flex_pattern.search(audited_text):
                    audited_text = flex_pattern.sub(item.proposed_fix, audited_text, count=1)
                elif item.verdict in ("false", "misleading") or item.severity in (
                    "S1",
                    "S3",
                    "S5",
                ):
                    has_unresolved_blockers = True
            elif item.verdict in ("false", "misleading") or item.severity in ("S1", "S3", "S5"):
                # Critical factual error or logic fallacy without fix is a blocker
                has_unresolved_blockers = True

    # Normalize whitespace and spacing before punctuation
    cleaned_text = re.sub(r"[ \t]+", " ", audited_text)
    cleaned_text = re.sub(r"\s+([.,;!?])", r"\1", cleaned_text)
    cleaned_text = re.sub(r"\n\s*\n\s*\n+", "\n\n", cleaned_text).strip()

    fact_check_passed = not has_unresolved_blockers
    return cleaned_text, removed_count, fact_check_passed


def audit_lesson_draft(
    draft_text: str,
    slides: list[SlideChunk],
    syllabus: SyllabusModule,
    client: StructuredLLMClient,
    prompt: str | None = None,
) -> FactCheckResult:
    """Performs adversarial factual audit on lesson draft text using StructuredLLMClient.

    Args:
        draft_text: Lesson draft prose to audit.
        slides: Primary source slide chunks.
        syllabus: Anchoring syllabus module.
        client: Implementation conforming to StructuredLLMClient protocol.
        prompt: Optional system prompt override. Defaults to loaded prompt.

    Returns:
        FactCheckResult containing audit items, status, and remediated text.

    Raises:
        Exception: If LLM call or schema validation fails.
    """
    system_prompt = prompt or get_fact_checker_prompt()
    user_prompt = format_fact_checker_user_prompt(
        draft_text=draft_text,
        slides=slides,
        syllabus=syllabus,
    )

    response: AuditClaimsResponse = client.generate_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_model=AuditClaimsResponse,
    )

    audited_markdown, removed_count, passed = apply_audit_remediations(
        raw_text=draft_text,
        audit_items=response.claims,
    )

    return FactCheckResult(
        audit_items=list(response.claims),
        fact_check_passed=passed,
        removed_unsupported_claims=removed_count,
        audited_markdown=audited_markdown,
    )


def fact_check_node(
    state: LessonPipelineState,
    client: StructuredLLMClient,
) -> LessonPipelineState:
    """Graph node executor for the fact-checking stage within the lesson pipeline.

    Audits state.raw_draft against state.slides and state.syllabus, updates audit_items,
    tracks removed unsupported claims, and assigns audited_markdown.

    Args:
        state: Pipeline state prior to factual auditing.
        client: Structured LLM client implementation.

    Returns:
        Updated LessonPipelineState containing factual audit results.

    Raises:
        Exception: If auditing fails.
    """
    raw_draft = state.raw_draft or ""
    result = audit_lesson_draft(
        draft_text=raw_draft,
        slides=state.slides,
        syllabus=state.syllabus,
        client=client,
    )

    state.audit_items = list(result.audit_items)
    state.fact_check_passed = result.fact_check_passed
    state.removed_unsupported_claims = result.removed_unsupported_claims
    state.audited_markdown = result.audited_markdown
    return state


__all__ = [
    "DEFAULT_FACT_CHECKER_PROMPT_PATH",
    "apply_audit_remediations",
    "audit_lesson_draft",
    "fact_check_node",
    "format_fact_checker_user_prompt",
    "get_fact_checker_prompt",
]
