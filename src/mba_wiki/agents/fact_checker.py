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


def normalize_claim_punctuation(text: str) -> str:
    """Normalizes quotation marks and punctuation variants for resilient matching.

    Args:
        text: Input text string.

    Returns:
        Normalized text with standardized quotes and dashes.

    Raises:
        None.
    """
    normalized = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return normalized.replace("—", "-").replace("–", "-")


def locate_and_apply_remediation(
    text: str,
    quote: str,
    replacement: str | None = None,
) -> tuple[str, bool]:
    """Locates a cited quote in draft text and removes or substitutes it reliably.

    Attempts exact match, whitespace/newline flexible match, and punctuation-tolerant
    normalized regex match. If replacement is None, removes the matched segment
    along with surrounding extra whitespace. If replacement is a string, substitutes
    the matched segment with the replacement string.

    Args:
        text: The draft prose being remediated.
        quote: The exact or slightly varied sentence/claim cited by the auditor LLM.
        replacement: String to replace the quote with, or None to prune/delete it.

    Returns:
        Tuple of (remediated_text, success_flag).

    Raises:
        None.
    """
    clean_quote = quote.strip()
    if not clean_quote:
        return text, False

    # 1. Exact string match
    if clean_quote in text:
        if replacement is None:
            pattern = re.escape(clean_quote)
            result = re.sub(rf"\s*{pattern}\s*", " ", text, count=1)
            return result, True
        return text.replace(clean_quote, replacement, 1), True

    # 2. Whitespace and newline flexible regex match
    quote_words = [re.escape(w) for w in clean_quote.split()]
    if quote_words:
        flex_pattern = re.compile(r"\s+".join(quote_words))
        if flex_pattern.search(text):
            if replacement is None:
                result = flex_pattern.sub(" ", text, count=1)
                return result, True
            return flex_pattern.sub(replacement, text, count=1), True

    # 3. Punctuation and quote-normalized tolerant match
    norm_quote = normalize_claim_punctuation(clean_quote)
    norm_tokens = [
        re.escape(t.strip(".,;:?!\"'")) for t in norm_quote.split() if t.strip(".,;:?!\"'")
    ]
    if norm_tokens:
        token_pattern = re.compile(
            r"\b" + r"[\s\.,;:?!\"'“”‘’—–-]+".join(norm_tokens) + r"[!?:;.]?"
        )
        match = token_pattern.search(text)
        if match:
            start, end = match.span()
            if replacement is None:
                result = text[:start] + " " + text[end:]
                return result, True
            return text[:start] + replacement + text[end:], True

    return text, False


def apply_audit_remediations(
    raw_text: str,
    audit_items: list[ClaimAuditItem],
) -> tuple[str, int, bool]:
    """Applies factual corrections and prunes unsupported claims from draft text.

    For unsupported claims (S4), removes the quote from the text and tracks count.
    If an unsupported claim cannot be located, flags has_unresolved_blockers to prevent
    silent bypass. For false or imprecise claims (S1, S2) with proposed_fix, replaces
    quote with fix. If a proposed fix cannot be located and applied, flags as blocker.

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
        # Check for unsupported claims (S4)
        if item.verdict == "unsupported" or item.severity == "S4":
            new_text, matched = locate_and_apply_remediation(
                text=audited_text,
                quote=item.quote,
                replacement=None,
            )
            if matched:
                audited_text = new_text
                removed_count += 1
            else:
                has_unresolved_blockers = True
            continue

        # Check for false, imprecise, or misleading claims
        if item.verdict in ("false", "imprecise", "misleading") or item.severity in (
            "S1",
            "S2",
            "S3",
            "S5",
        ):
            if item.proposed_fix:
                new_text, matched = locate_and_apply_remediation(
                    text=audited_text,
                    quote=item.quote,
                    replacement=item.proposed_fix,
                )
                if matched:
                    audited_text = new_text
                else:
                    has_unresolved_blockers = True
            elif item.verdict in ("false", "misleading") or item.severity in ("S1", "S3", "S5"):
                # Critical factual error or logic fallacy without fix is a blocker
                has_unresolved_blockers = True
            elif item.verdict == "imprecise" or item.severity == "S2":
                # Imprecise claim without fix is an unresolved issue
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
    "locate_and_apply_remediation",
    "normalize_claim_punctuation",
]
