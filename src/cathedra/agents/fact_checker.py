"""Factual auditing agent node for verifying lesson drafts against source materials.

Extracts objective claims, cross-references statements against presentation slides
and course syllabus guidelines, classifies discrepancies from S1 to S6, prunes
unsupported (S4) claims, applies factual fixes, and updates pipeline state.
"""

import re
from pathlib import Path

from cathedra.agents.llm_client import StructuredLLMClient
from cathedra.schemas import (
    AtomicZettel,
    AuditClaimsResponse,
    ClaimAuditItem,
    DialecticalTension,
    FactCheckResult,
    GuardrailResponse,
    LessonPipelineState,
    SlideChunk,
    SyllabusModule,
    VideoTranscript,
)

DEFAULT_FACT_CHECKER_PROMPT_PATH = Path(__file__).parent / "prompts" / "fact_checker.md"
DEFAULT_INVARIANCE_PROMPT_PATH = Path(__file__).parent / "prompts" / "fact_checker_invariance.md"


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


def get_invariance_prompt(prompt_path: Path | None = None) -> str:
    """Loads the post-humanizer invariance audit prompt from an external markdown file.

    Args:
        prompt_path: Optional explicit path to invariance prompt file.
            Defaults to DEFAULT_INVARIANCE_PROMPT_PATH.

    Returns:
        String content of the invariance prompt markdown file.

    Raises:
        FileNotFoundError: If the specified prompt file cannot be found on disk.
    """
    resolved_path = prompt_path or DEFAULT_INVARIANCE_PROMPT_PATH
    if not resolved_path.is_file():
        raise FileNotFoundError(f"Invariance audit prompt file not found: {resolved_path}")
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

    # 1. Official Course Guidelines (scope only; bibliography is intentionally omitted)
    topics_list = "\n".join(f"- {t}" for t in syllabus.topics)
    syllabus_sec = (
        f"## Fonte 1: Escopo Curricular da Disciplina\n"
        f"Disciplina: {syllabus.discipline_name} (slug: `{syllabus.discipline_slug}`)\n\n"
        f"### Resumo da Ementa\n{syllabus.syllabus_summary}\n\n"
        f"### Tópicos Curriculares\n{topics_list}"
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
        header = (
            f"## Fonte 3: Transcrição da Fala do Professor na Videoaula\n"
            f"Duração gravada: {duration_min:.1f} minutos | "
            f"Arquivo de origem: `{transcript.source_filename}`"
        )
        if transcript.segments:
            segment_lines = [f"[{seg.id}] {seg.text_cleaned}" for seg in transcript.segments]
            sections.append(f"{header}\n\n" + "\n".join(segment_lines))
        else:
            sections.append(f"{header}\n\n{transcript.full_text_cleaned}")

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
    if not quote:
        return None
    cleaned_quote = quote.strip(" \t\r\n`\"'“”‘’")
    if not cleaned_quote:
        return None

    def contains(text: str) -> bool:
        return " ".join(cleaned_quote.split()).casefold() in " ".join(text.split()).casefold()

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

        # Minor stylistic notes (S6) are non-blocking unless verdict is false/unsupported/misleading
        if item.severity == "S6" and item.verdict not in ("false", "unsupported", "misleading"):
            if item.proposed_fix:
                new_text, matched = locate_and_apply_remediation(
                    text=audited_text,
                    quote=item.quote,
                    replacement=item.proposed_fix,
                )
                if matched:
                    audited_text = new_text
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
                # Guardrail mode: S2 observation without a proposed fix is logged without blocking
                continue

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


def _matches_any_zettel(zettels: list[AtomicZettel] | None, quote: str) -> bool:
    """Checks whether a claim quote matches the title or body of any atomic zettel.

    Args:
        zettels: Optional list of AtomicZettel instances to inspect.
        quote: Claim quote string to search for.

    Returns:
        True if any zettel matches the quote, False otherwise.

    Raises:
        None.
    """
    for zettel in zettels or []:
        _, matches_content = locate_and_apply_remediation(zettel.content_markdown, quote)
        _, matches_title = locate_and_apply_remediation(zettel.title, quote)
        if matches_content or matches_title:
            return True
    return False


def _matches_any_tension(tensions: list[DialecticalTension] | None, quote: str) -> bool:
    """Checks whether a claim quote matches any textual field of a dialectical tension.

    Args:
        tensions: Optional list of DialecticalTension instances to inspect.
        quote: Claim quote string to search for.

    Returns:
        True if any tension matches the quote, False otherwise.

    Raises:
        None.
    """
    for tension in tensions or []:
        combined = (
            f"{tension.title} {tension.pole_a_framework} {tension.pole_a_thesis} "
            f"{tension.pole_b_framework} {tension.pole_b_thesis} {tension.synthesis_guidelines}"
        )
        _, matches = locate_and_apply_remediation(combined, quote)
        if matches:
            return True
    return False


def _has_unresolved_critical_claims(
    claims: list[ClaimAuditItem],
    draft_text: str,
    audited_markdown: str,
    original_zettels: list[AtomicZettel] | None = None,
    valid_zettels: list[AtomicZettel] | None = None,
    original_tensions: list[DialecticalTension] | None = None,
    valid_tensions: list[DialecticalTension] | None = None,
) -> bool:
    """Checks whether any critical S1/S5/false claim remained unresolved across all artifacts.

    Inspects draft prose, zettels, tensions, and orphan claims (quotes not found anywhere)
    so tolerant publication modes cannot bypass unresolved critical factual errors.

    Args:
        claims: Complete list of audited claims produced by the guardrail.
        draft_text: Original unedited lesson draft prose.
        audited_markdown: Remediated lesson prose after applying fixes.
        original_zettels: Candidate zettels prior to filtering/remediation.
        valid_zettels: Surviving zettels after filtering/remediation.
        original_tensions: Candidate tensions prior to filtering.
        valid_tensions: Surviving tensions after filtering.

    Returns:
        True if at least one critical S1/S5/false claim remained unresolved.

    Raises:
        None.
    """
    for item in claims:
        if item.verdict != "false" and item.severity not in ("S1", "S5"):
            continue
        _, was_in_draft = locate_and_apply_remediation(draft_text, item.quote)
        was_in_zettel = _matches_any_zettel(original_zettels, item.quote)
        was_in_tension = _matches_any_tension(original_tensions, item.quote)
        if not (was_in_draft or was_in_zettel or was_in_tension):
            return True
        if was_in_draft:
            if not item.proposed_fix:
                return True
            _, still_in_draft = locate_and_apply_remediation(audited_markdown, item.quote)
            if still_in_draft:
                return True
        if was_in_zettel and _matches_any_zettel(valid_zettels, item.quote):
            return True
        if was_in_tension and _matches_any_tension(valid_tensions, item.quote):
            return True
    return False


def _evaluate_audit_claims(
    response: AuditClaimsResponse,
    draft_text: str,
    slides: list[SlideChunk],
    syllabus: SyllabusModule,
    zettels: list[AtomicZettel] | None,
    tensions: list[DialecticalTension] | None,
    transcript: VideoTranscript | None,
    allow_pending_review: bool = False,
) -> FactCheckResult:
    """Evaluates guardrail deviations deterministically without mutating caller inputs.

    Args:
        response: Mapped AuditClaimsResponse containing deviations from the guardrail.
        draft_text: Preliminary lesson draft prose to remediate.
        slides: Primary source slide chunks.
        syllabus: Anchoring syllabus module.
        zettels: Optional candidate atomic zettels to filter/remediate.
        tensions: Optional candidate dialectical tensions to filter.
        transcript: Optional consolidated lecture speech transcript.
        allow_pending_review: Whether non-critical unresolved items may pass with flag.

    Returns:
        Consolidated FactCheckResult with remediated markdown and validated artifacts.

    Raises:
        None.
    """
    working_zettels = [z.model_copy(deep=True) for z in zettels] if zettels else []
    working_tensions = [t.model_copy(deep=True) for t in tensions] if tensions else []

    for item in response.claims:
        item.evidence_status = "pending_review"
        if item.verdict == "verified":
            source = locate_evidence_source(item, slides, syllabus, transcript)
            item.evidence_source = source
            if source is not None:
                item.evidence_status = "material_supported"

    draft_claims: list[ClaimAuditItem] = []
    has_orphan_blockers = False

    for item in response.claims:
        _, matches_draft = locate_and_apply_remediation(draft_text, item.quote)
        if matches_draft:
            draft_claims.append(item)
            continue

        matched_in_secondary = _matches_any_zettel(
            working_zettels, item.quote
        ) or _matches_any_tension(working_tensions, item.quote)

        is_blocking_item = (
            item.verdict in ("unsupported", "false", "misleading")
            or item.severity in ("S1", "S3", "S4", "S5")
            or (
                (item.verdict == "imprecise" or item.severity == "S2")
                and item.proposed_fix is not None
            )
        )
        if not matched_in_secondary and is_blocking_item:
            has_orphan_blockers = True

    audited_markdown, removed_count_draft, draft_passed = apply_audit_remediations(
        raw_text=draft_text,
        audit_items=draft_claims,
    )

    valid_zettels: list[AtomicZettel] = []
    removed_count_zettels = 0
    zettels_blockers = False
    if working_zettels:
        valid_zettels, removed_count_zettels, zettels_blockers = filter_and_remediate_zettels(
            zettels=working_zettels,
            audit_items=response.claims,
        )

    valid_tensions: list[DialecticalTension] = []
    removed_count_tensions = 0
    tensions_blockers = False
    if working_tensions:
        valid_tensions, removed_count_tensions, tensions_blockers = filter_and_remediate_tensions(
            tensions=working_tensions,
            audit_items=response.claims,
        )

    total_removed = removed_count_draft + removed_count_zettels + removed_count_tensions
    strict_passed = (
        draft_passed and not zettels_blockers and not tensions_blockers and not has_orphan_blockers
    )
    has_critical = _has_unresolved_critical_claims(
        claims=response.claims,
        draft_text=draft_text,
        audited_markdown=audited_markdown,
        original_zettels=zettels,
        valid_zettels=valid_zettels,
        original_tensions=tensions,
        valid_tensions=valid_tensions,
    )
    if allow_pending_review and not strict_passed and not has_critical:
        overall_passed = True
        has_pending_review = True
    else:
        overall_passed = strict_passed
        has_pending_review = False

    return FactCheckResult(
        audit_items=list(response.claims),
        fact_check_passed=overall_passed,
        has_pending_review=has_pending_review,
        removed_unsupported_claims=total_removed,
        audited_markdown=audited_markdown,
        validated_zettels=valid_zettels,
        validated_tensions=valid_tensions,
    )


def audit_lesson_draft(
    draft_text: str,
    slides: list[SlideChunk],
    syllabus: SyllabusModule,
    client: StructuredLLMClient,
    prompt: str | None = None,
    zettels: list[AtomicZettel] | None = None,
    tensions: list[DialecticalTension] | None = None,
    transcript: VideoTranscript | None = None,
    allow_pending_review: bool = False,
) -> FactCheckResult:
    """Performs single-pass anti-hallucination guardrail audit on lesson draft artifacts.

    Args:
        draft_text: Lesson draft prose to audit.
        slides: Primary source slide chunks.
        syllabus: Anchoring syllabus module.
        client: Implementation conforming to StructuredLLMClient protocol.
        prompt: Optional system prompt override. Defaults to loaded guardrail prompt.
        zettels: Optional candidate atomic zettels to audit.
        tensions: Optional candidate dialectical tensions to audit.
        transcript: Optional consolidated speech transcript of the recorded lecture.
        allow_pending_review: Whether non-critical unresolved items may pass with flag.

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

    guardrail_response: GuardrailResponse = client.generate_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_model=GuardrailResponse,
    )
    response = guardrail_response.to_audit_claims_response()
    return _evaluate_audit_claims(
        response=response,
        draft_text=draft_text,
        slides=slides,
        syllabus=syllabus,
        zettels=zettels,
        tensions=tensions,
        transcript=transcript,
        allow_pending_review=allow_pending_review,
    )


def audit_humanized_invariance(
    audited_markdown: str,
    humanized_markdown: str,
    client: StructuredLLMClient,
    zettels: list[AtomicZettel] | None = None,
    tensions: list[DialecticalTension] | None = None,
    prompt: str | None = None,
    allow_pending_review: bool = False,
) -> FactCheckResult:
    """Verifies that post-humanizer text preserves factual invariance against audited prose.

    Args:
        audited_markdown: Previously verified and remediated lesson prose.
        humanized_markdown: Stylistically rewritten prose produced by humanize_node.
        client: Structured LLM client for invariance verification.
        zettels: Validated atomic zettels to include in final invariance check.
        tensions: Validated dialectical tensions to include in final invariance check.
        prompt: Optional system prompt override.

    Returns:
        FactCheckResult recording invariance audit items and pass/fail status.

    Raises:
        Exception: If LLM call or schema validation fails.
    """
    system_prompt = prompt or get_invariance_prompt()
    sections = [
        f"## Texto Auditado (Referência Aprovada)\n\n```markdown\n{audited_markdown}\n```",
        f"## Texto Humanizado (Alvo da Verificação)\n\n```markdown\n{humanized_markdown}\n```",
    ]
    if zettels:
        z_lines = [f"- [{z.slug}] {z.title}: {z.content_markdown}" for z in zettels]
        sections.append("## Zettels Finais\n" + "\n".join(z_lines))
    if tensions:
        t_lines = [
            f"- [{t.slug}] {t.title}: {t.pole_a_thesis} vs {t.pole_b_thesis}" for t in tensions
        ]
        sections.append("## Tensões Finais\n" + "\n".join(t_lines))

    response: AuditClaimsResponse = client.generate_structured(
        system_prompt=system_prompt,
        user_prompt="\n\n".join(sections),
        response_model=AuditClaimsResponse,
    )
    has_blocking = any(
        item.verdict != "verified" or (item.severity is not None and item.severity != "S6")
        for item in response.claims
    )
    has_critical = any(
        item.verdict == "false" or item.severity in ("S1", "S5") for item in response.claims
    )
    if allow_pending_review and has_blocking and not has_critical:
        passed = True
        has_pending_review = True
    else:
        passed = not has_blocking
        has_pending_review = False
    return FactCheckResult(
        audit_items=list(response.claims),
        fact_check_passed=passed,
        has_pending_review=has_pending_review,
        removed_unsupported_claims=0,
        audited_markdown=humanized_markdown,
        validated_zettels=list(zettels or []),
        validated_tensions=list(tensions or []),
    )


def fact_check_node(
    state: LessonPipelineState,
    client: StructuredLLMClient,
    allow_pending_review: bool = False,
) -> LessonPipelineState:
    """Graph node executor for the anti-hallucination guardrail stage in the lesson pipeline.

    Audits state.raw_draft, state.extracted_zettels, and state.detected_tensions
    against slides and lecture transcript in a single pass, updates audit_items,
    prunes ungrounded entities, and updates pipeline state with validated outputs.

    Args:
        state: Pipeline state prior to factual auditing.
        client: Structured LLM client implementation.
        allow_pending_review: Whether non-critical unresolved items may pass with flag.

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
        allow_pending_review=allow_pending_review,
    )

    state.audit_items = list(result.audit_items)
    state.fact_check_passed = result.fact_check_passed
    state.has_pending_review = result.has_pending_review
    state.removed_unsupported_claims = result.removed_unsupported_claims
    state.audited_markdown = result.audited_markdown
    state.extracted_zettels = result.validated_zettels
    state.detected_tensions = result.validated_tensions
    return state


__all__ = [
    "DEFAULT_FACT_CHECKER_PROMPT_PATH",
    "DEFAULT_INVARIANCE_PROMPT_PATH",
    "apply_audit_remediations",
    "audit_humanized_invariance",
    "audit_lesson_draft",
    "fact_check_node",
    "filter_and_remediate_tensions",
    "filter_and_remediate_zettels",
    "format_fact_checker_user_prompt",
    "get_fact_checker_prompt",
    "get_invariance_prompt",
    "locate_and_apply_remediation",
    "normalize_claim_punctuation",
]
