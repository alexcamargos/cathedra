"""Factual auditing agent node for verifying lesson drafts against source materials.

Extracts objective claims, cross-references statements against presentation slides
and course syllabus guidelines, classifies discrepancies from S1 to S6, prunes
unsupported (S4) claims, applies factual fixes, and updates pipeline state.
"""

import re
from pathlib import Path

from mba_wiki.agents.llm_client import StructuredLLMClient
from mba_wiki.schemas import (
    AtomicZettel,
    AuditClaimsResponse,
    ClaimAuditItem,
    DialecticalTension,
    FactCheckResult,
    LessonPipelineState,
    SlideChunk,
    SyllabusModule,
    VideoTranscript,
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
    zettels: list[AtomicZettel] | None = None,
    tensions: list[DialecticalTension] | None = None,
    transcript: VideoTranscript | None = None,
) -> str:
    """Formats contextual input payload containing draft prose and source materials.

    Args:
        draft_text: Preliminary lesson draft prose to audit.
        slides: Primary source slide chunks containing text, tables, and LaTeX equations.
        syllabus: Anchoring syllabus module with official scope and bibliography.
        zettels: Optional list of candidate atomic zettels to audit.
        tensions: Optional list of candidate dialectical tensions to audit.
        transcript: Optional consolidated speech transcript of the recorded lecture.

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
        f"## Fonte 1: Ementa estruturada e lista bibliográfica não consultada\n"
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

    # 3. Speech Transcript (if present)
    if transcript:
        duration_min = transcript.duration_seconds / 60
        transcript_parts: list[str] = [
            f"## Fonte 3: Transcrição da Fala do Professor na Videoaula\n"
            f"Duração gravada: {duration_min:.1f} minutos | "
            f"Arquivo de origem: `{transcript.source_filename}`\n\n"
            f"{transcript.full_text_cleaned}"
        ]
        for segment in transcript.segments:
            transcript_parts.append(
                f"### Segmento {segment.id} ({segment.start:.1f}s–{segment.end:.1f}s)\n"
                f"Transcrição bruta: {segment.text_raw}\n"
                f"Transcrição limpa: {segment.text_cleaned}"
            )
        sections.append("\n\n".join(transcript_parts))

    # 4. Draft Text to Audit
    draft_sec = f"## Rascunho da Aula a ser Auditado\n\n```markdown\n{draft_text}\n```"
    sections.append(draft_sec)

    # 4. Atomic Zettels (if present)
    if zettels:
        zettel_parts: list[str] = ["## Conceitos Atômicos (Zettels) a serem Auditados"]
        for z in zettels:
            zettel_parts.append(
                f"### [Zettel: {z.slug}] {z.title}\n"
                f"Tags: {', '.join(z.domain_tags)}\n\n"
                f"{z.content_markdown}"
            )
        sections.append("\n\n".join(zettel_parts))

    # 5. Dialectical Tensions (if present)
    if tensions:
        tension_parts: list[str] = ["## Tensões Dialéticas a serem Auditadas"]
        for t in tensions:
            tension_parts.append(
                f"### [Tensão: {t.slug}] {t.title}\n"
                f"- Polo A ({t.pole_a_discipline}): {t.pole_a_framework} - {t.pole_a_thesis}\n"
                f"- Polo B ({t.pole_b_discipline}): {t.pole_b_framework} - {t.pole_b_thesis}\n"
                f"- Natureza: {t.tension_nature}\n"
                f"- Síntese: {t.synthesis_guidelines}"
            )
        sections.append("\n\n".join(tension_parts))

    return "\n\n".join(sections)


def locate_evidence_source(
    item: ClaimAuditItem,
    slides: list[SlideChunk],
    syllabus: SyllabusModule,
    transcript: VideoTranscript | None,
) -> str | None:
    """Return a canonical location only if the excerpt occurs in supplied material."""
    quote = item.evidence_quote
    if not quote or not quote.strip():
        return None

    def contains(text: str) -> bool:
        return " ".join(quote.split()).casefold() in " ".join(text.split()).casefold()

    if item.evidence_kind == "slide" and item.evidence_locator is not None:
        matching_slides = [slide for slide in slides if slide.slide_number == item.evidence_locator]
        if len(matching_slides) == 1:
            slide = matching_slides[0]
            if contains(slide.raw_text) or any(contains(eq) for eq in slide.latex_equations):
                return f"Slide {slide.slide_number}"
    elif item.evidence_kind == "syllabus" and item.evidence_locator is None:
        if contains(syllabus.syllabus_summary) or any(contains(topic) for topic in syllabus.topics):
            return "Ementa estruturada"
    elif item.evidence_kind == "transcript" and transcript is not None:
        if transcript.segments and item.evidence_locator is not None:
            matching_segments = [
                segment for segment in transcript.segments if segment.id == item.evidence_locator
            ]
            if len(matching_segments) == 1:
                segment = matching_segments[0]
                if contains(segment.text_raw) or contains(segment.text_cleaned):
                    return (
                        f"Transcrição {transcript.source_filename}, segmento {segment.id} "
                        f"({segment.start:.1f}s–{segment.end:.1f}s)"
                    )
        elif not transcript.segments and item.evidence_locator is None:
            if contains(transcript.full_text_raw) or contains(transcript.full_text_cleaned):
                return f"Transcrição {transcript.source_filename}, sem timestamps"
    return None


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


def filter_and_remediate_zettels(
    zettels: list[AtomicZettel],
    audit_items: list[ClaimAuditItem],
) -> tuple[list[AtomicZettel], int, bool]:
    """Filters or remediates atomic zettels against audited factual claim items.

    Prunes zettels that contain unresolvable critical claims (S1 or S4 without resolution),
    applies proposed fixes where available, and records whether any unresolved blocker remains.

    Args:
        zettels: Candidate atomic zettels extracted from the lesson.
        audit_items: Complete collection of claims evaluated by the auditor.

    Returns:
        Tuple containing (validated_zettels, removed_unsupported_count, has_blockers).

    Raises:
        None.
    """
    validated: list[AtomicZettel] = []
    removed_count = 0
    has_blockers = False

    for zettel in zettels:
        zettel_text = zettel.content_markdown
        discard_zettel = False

        for item in audit_items:
            _, matches_content = locate_and_apply_remediation(zettel_text, item.quote)
            _, matches_title = locate_and_apply_remediation(zettel.title, item.quote)
            if not (matches_content or matches_title):
                continue

            if item.verdict == "unsupported" or item.severity == "S4":
                discard_zettel = True
                removed_count += 1
                break
            elif item.verdict in ("false", "misleading") or item.severity in ("S1", "S3", "S5"):
                if item.proposed_fix:
                    new_text, replaced = locate_and_apply_remediation(
                        text=zettel_text,
                        quote=item.quote,
                        replacement=item.proposed_fix,
                    )
                    if replaced:
                        zettel_text = new_text
                    else:
                        discard_zettel = True
                        has_blockers = True
                        break
                else:
                    discard_zettel = True
                    break
            elif item.verdict == "imprecise" or item.severity in ("S2", "S6"):
                if item.proposed_fix:
                    new_text, replaced = locate_and_apply_remediation(
                        text=zettel_text,
                        quote=item.quote,
                        replacement=item.proposed_fix,
                    )
                    if replaced:
                        zettel_text = new_text

        if not discard_zettel:
            zettel.content_markdown = zettel_text
            validated.append(zettel)

    return validated, removed_count, has_blockers


def filter_and_remediate_tensions(
    tensions: list[DialecticalTension],
    audit_items: list[ClaimAuditItem],
) -> tuple[list[DialecticalTension], int, bool]:
    """Filters or remediates dialectical tensions against audited factual claim items.

    Prunes tensions containing false frameworks (S1) or unsupported inventions (S4).

    Args:
        tensions: Candidate dialectical tensions identified during drafting.
        audit_items: Complete collection of claims evaluated by the auditor.

    Returns:
        Tuple containing (validated_tensions, removed_unsupported_count, has_blockers).

    Raises:
        None.
    """
    validated: list[DialecticalTension] = []
    removed_count = 0
    has_blockers = False

    for tension in tensions:
        combined = (
            f"{tension.title} {tension.pole_a_framework} {tension.pole_a_thesis} "
            f"{tension.pole_b_framework} {tension.pole_b_thesis} {tension.synthesis_guidelines}"
        )
        discard_tension = False

        for item in audit_items:
            _, matches = locate_and_apply_remediation(combined, item.quote)
            if not matches:
                continue

            if item.verdict == "unsupported" or item.severity == "S4":
                discard_tension = True
                removed_count += 1
                break
            elif item.verdict in ("false", "misleading") or item.severity in ("S1", "S3", "S5"):
                discard_tension = True
                break

        if not discard_tension:
            validated.append(tension)

    return validated, removed_count, has_blockers


def audit_lesson_draft(
    draft_text: str,
    slides: list[SlideChunk],
    syllabus: SyllabusModule,
    client: StructuredLLMClient,
    prompt: str | None = None,
    zettels: list[AtomicZettel] | None = None,
    tensions: list[DialecticalTension] | None = None,
    transcript: VideoTranscript | None = None,
) -> FactCheckResult:
    """Performs adversarial factual audit on lesson draft text using StructuredLLMClient.

    Args:
        draft_text: Lesson draft prose to audit.
        slides: Primary source slide chunks.
        syllabus: Anchoring syllabus module.
        client: Implementation conforming to StructuredLLMClient protocol.
        prompt: Optional system prompt override. Defaults to loaded prompt.
        zettels: Optional candidate atomic zettels to audit.
        tensions: Optional candidate dialectical tensions to audit.
        transcript: Optional consolidated speech transcript of the recorded lecture.

    Returns:
        FactCheckResult containing audit items, status, remediated text, and validated collections.

    Raises:
        Exception: If LLM call or schema validation fails.
    """
    system_prompt = prompt or get_fact_checker_prompt()
    user_prompt = format_fact_checker_user_prompt(
        draft_text=draft_text,
        slides=slides,
        syllabus=syllabus,
        zettels=zettels,
        tensions=tensions,
        transcript=transcript,
    )

    response: AuditClaimsResponse = client.generate_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_model=AuditClaimsResponse,
    )

    evidence_blockers = False
    for item in response.claims:
        item.evidence_status = "pending_review"
        if item.verdict == "verified":
            source = locate_evidence_source(item, slides, syllabus, transcript)
            item.evidence_source = source
            if source is None:
                evidence_blockers = True
            else:
                item.evidence_status = "material_supported"

    # 1. Segregate claims matching raw_draft vs secondary artifacts
    draft_claims: list[ClaimAuditItem] = []
    has_orphan_blockers = False

    for item in response.claims:
        _, matches_draft = locate_and_apply_remediation(draft_text, item.quote)
        if matches_draft:
            draft_claims.append(item)
            continue

        # Check if the claim belongs to candidate zettels or tensions
        matched_in_secondary = False
        for z in zettels or []:
            _, m_c = locate_and_apply_remediation(z.content_markdown, item.quote)
            _, m_t = locate_and_apply_remediation(z.title, item.quote)
            if m_c or m_t:
                matched_in_secondary = True
                break

        if not matched_in_secondary:
            for t in tensions or []:
                combined_t = (
                    f"{t.title} {t.pole_a_framework} {t.pole_a_thesis} "
                    f"{t.pole_b_framework} {t.pole_b_thesis} {t.synthesis_guidelines}"
                )
                _, m_tens = locate_and_apply_remediation(combined_t, item.quote)
                if m_tens:
                    matched_in_secondary = True
                    break

        if not matched_in_secondary and (
            item.verdict in ("unsupported", "false", "misleading", "imprecise")
            or item.severity in ("S1", "S2", "S3", "S4", "S5")
        ):
            has_orphan_blockers = True

    audited_markdown, removed_count_draft, draft_passed = apply_audit_remediations(
        raw_text=draft_text,
        audit_items=draft_claims,
    )

    valid_zettels: list[AtomicZettel] = []
    removed_count_zettels = 0
    zettels_blockers = False
    if zettels:
        valid_zettels, removed_count_zettels, zettels_blockers = filter_and_remediate_zettels(
            zettels=zettels,
            audit_items=response.claims,
        )

    valid_tensions: list[DialecticalTension] = []
    removed_count_tensions = 0
    tensions_blockers = False
    if tensions:
        valid_tensions, removed_count_tensions, tensions_blockers = filter_and_remediate_tensions(
            tensions=tensions,
            audit_items=response.claims,
        )

    total_removed = removed_count_draft + removed_count_zettels + removed_count_tensions
    overall_passed = (
        draft_passed
        and not zettels_blockers
        and not tensions_blockers
        and not has_orphan_blockers
        and not evidence_blockers
    )

    return FactCheckResult(
        audit_items=list(response.claims),
        fact_check_passed=overall_passed,
        removed_unsupported_claims=total_removed,
        audited_markdown=audited_markdown,
        validated_zettels=valid_zettels,
        validated_tensions=valid_tensions,
    )


def fact_check_node(
    state: LessonPipelineState,
    client: StructuredLLMClient,
) -> LessonPipelineState:
    """Graph node executor for the fact-checking stage within the lesson pipeline.

    Audits state.raw_draft, state.extracted_zettels, and state.detected_tensions
    against slides and syllabus, updates audit_items, prunes ungrounded entities,
    and updates pipeline state with validated outputs.

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
        zettels=state.extracted_zettels,
        tensions=state.detected_tensions,
        transcript=state.transcript,
    )

    state.audit_items = list(result.audit_items)
    state.fact_check_passed = result.fact_check_passed
    state.removed_unsupported_claims = result.removed_unsupported_claims
    state.audited_markdown = result.audited_markdown
    state.extracted_zettels = result.validated_zettels
    state.detected_tensions = result.validated_tensions
    return state


__all__ = [
    "DEFAULT_FACT_CHECKER_PROMPT_PATH",
    "apply_audit_remediations",
    "audit_lesson_draft",
    "fact_check_node",
    "filter_and_remediate_tensions",
    "filter_and_remediate_zettels",
    "format_fact_checker_user_prompt",
    "get_fact_checker_prompt",
    "locate_and_apply_remediation",
    "normalize_claim_punctuation",
]
