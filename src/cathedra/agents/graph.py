"""Pipeline graph orchestrator connecting ingestion, drafting, auditing, and humanizing.

Coordinates sequential execution of typed pipeline stages on LessonPipelineState,
enforcing factual integrity and stylistic quality before returning a validated WikiLessonOutput.
"""

import re
import unicodedata
from datetime import date
from pathlib import Path

from cathedra.agents.drafter import draft_node
from cathedra.agents.fact_checker import audit_humanized_invariance, fact_check_node
from cathedra.agents.humanizer import humanize_node
from cathedra.agents.llm_client import StructuredLLMClient
from cathedra.ingestion.slide_parser import infer_slide_title, parse_slides
from cathedra.schemas import (
    LessonPipelineState,
    SlideChunk,
    StructuredSyllabus,
    SyllabusModule,
    VideoTranscript,
    WikiLessonOutput,
)


class FactCheckBlockedError(RuntimeError):
    """A factual audit failed; retain the audited state for reporting."""

    def __init__(self, state: LessonPipelineState) -> None:
        super().__init__("A auditoria factual possui bloqueadores não resolvidos.")
        self.state = state


def slugify(text: str) -> str:
    """Normalizes string to lowercase ASCII slug format, replacing punctuation with hyphens.

    Args:
        text: Arbitrary input string to be slugified.

    Returns:
        URL-safe and filesystem-safe lowercase slug string.

    Raises:
        None.
    """
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^\w\s-]", "", normalized).strip().lower()
    return re.sub(r"[-\s]+", "-", cleaned)


def find_syllabus_module(
    syllabus: StructuredSyllabus,
    discipline_slug: str,
) -> SyllabusModule:
    """Locates a syllabus module within a StructuredSyllabus instance by discipline slug.

    Args:
        syllabus: Structured syllabus container containing modules.
        discipline_slug: Slug identifier of the target discipline.

    Returns:
        The matching SyllabusModule instance.

    Raises:
        KeyError: If no module matching the slug is present in the syllabus.
    """
    for module in syllabus.modules:
        if module.discipline_slug == discipline_slug:
            return module
    raise KeyError(f"Discipline '{discipline_slug}' not found in structured syllabus.")


def create_initial_state(
    slides: list[SlideChunk],
    syllabus: SyllabusModule,
    lesson_number: int,
    lesson_title: str,
    source_slide_filename: str,
    lesson_slug: str | None = None,
    full_syllabus: StructuredSyllabus | None = None,
    transcript: VideoTranscript | None = None,
) -> LessonPipelineState:
    """Instantiates a fresh LessonPipelineState from in-memory slide chunks and syllabus.

    Args:
        slides: List of parsed SlideChunk models.
        syllabus: Anchoring SyllabusModule for the discipline.
        lesson_number: Sequential index of the lesson within the discipline.
        lesson_title: Descriptive title of the lesson theme.
        source_slide_filename: Basename of the presentation file.
        lesson_slug: Optional explicit slug. Defaults to slugified lesson_title.
        full_syllabus: Optional complete StructuredSyllabus of the MBA course.
        transcript: Optional speech transcript of the recorded lecture.

    Returns:
        An initialized LessonPipelineState ready for drafting.

    Raises:
        ValueError: If slides list is empty.
    """
    if not slides:
        raise ValueError("Cannot initialize pipeline state with empty slides list.")
    if transcript is not None:
        if transcript.discipline_slug != syllabus.discipline_slug:
            raise ValueError("A disciplina da transcrição não corresponde à disciplina da aula.")
        if transcript.lesson_number is not None and transcript.lesson_number != lesson_number:
            raise ValueError("O número da aula na transcrição não corresponde à aula solicitada.")

    computed_slug = lesson_slug or slugify(lesson_title)
    return LessonPipelineState(
        discipline_slug=syllabus.discipline_slug,
        discipline_name=syllabus.discipline_name,
        lesson_number=lesson_number,
        lesson_title=lesson_title,
        lesson_slug=computed_slug,
        source_slide_filename=source_slide_filename,
        slides=slides,
        syllabus=syllabus,
        full_syllabus=full_syllabus,
        transcript=transcript,
        source_transcript_binding="in_memory" if transcript is not None else None,
    )


def ingestion_node(
    slide_path: Path,
    syllabus: SyllabusModule,
    lesson_number: int,
    lesson_title: str | None = None,
    lesson_slug: str | None = None,
    full_syllabus: StructuredSyllabus | None = None,
    transcript: VideoTranscript | None = None,
    transcript_path: Path | None = None,
    require_transcript_lesson_number: bool = False,
) -> LessonPipelineState:
    """Ingestion graph node extracting slide chunks from disk and anchoring to syllabus.

    Args:
        slide_path: Path to the input presentation (PDF or PPTX).
        syllabus: Anchoring SyllabusModule for the target discipline.
        lesson_number: Sequential lesson number.
        lesson_title: Optional descriptive title of the lesson theme (inferred if None).
        lesson_slug: Optional custom slug for the lesson.
        full_syllabus: Optional complete StructuredSyllabus of the MBA course.
        transcript: Optional pre-loaded VideoTranscript instance.
        transcript_path: Optional path to a VideoTranscript JSON file on disk.
        require_transcript_lesson_number: Require explicit lesson identity for auto selection.

    Returns:
        Initial LessonPipelineState populated with parsed slide chunks and syllabus.

    Raises:
        FileNotFoundError: If the slide presentation file does not exist.
        ValueError: If file format is unsupported or contains no extractable slides.
    """
    if not slide_path.is_file():
        raise FileNotFoundError(f"Slide file not found: {slide_path}")

    if transcript is not None and transcript_path is not None:
        raise ValueError("Informe a transcrição em memória ou por caminho, não ambos.")
    resolved_transcript = transcript
    if transcript_path is not None:
        if not transcript_path.is_file():
            raise FileNotFoundError(f"Transcrição não encontrada: {transcript_path}")
        payload = transcript_path.read_text(encoding="utf-8")
        resolved_transcript = VideoTranscript.model_validate_json(payload)
    if require_transcript_lesson_number and (
        resolved_transcript is None or resolved_transcript.lesson_number is None
    ):
        raise ValueError("A transcrição automática precisa identificar o número da aula.")

    slides = parse_slides(slide_path)
    fallback_title = f"Aula {lesson_number:02d}"
    resolved_title = lesson_title or (
        infer_slide_title(slides[0].raw_text, default=fallback_title) if slides else fallback_title
    )
    state = create_initial_state(
        slides=slides,
        syllabus=syllabus,
        lesson_number=lesson_number,
        lesson_title=resolved_title,
        source_slide_filename=slide_path.name,
        lesson_slug=lesson_slug,
        full_syllabus=full_syllabus,
        transcript=resolved_transcript,
    )
    state.source_transcript_path = str(transcript_path.resolve()) if transcript_path else None
    if transcript_path is not None:
        state.source_transcript_binding = "auto" if require_transcript_lesson_number else "explicit"
    return state


def finalize_output_node(
    state: LessonPipelineState,
    processed_date: date | None = None,
) -> LessonPipelineState:
    """Final graph stage constructing WikiLessonOutput from processed state attributes.

    Args:
        state: Pipeline state after passing drafting, fact-checking, and humanizing.
        processed_date: Optional explicit processing date. Defaults to date.today().

    Returns:
        Updated LessonPipelineState with populated output attribute.

    Raises:
        None.
    """
    final_body = state.humanized_markdown or state.audited_markdown or state.raw_draft or ""

    output = WikiLessonOutput(
        discipline_slug=state.discipline_slug,
        discipline_name=state.discipline_name,
        lesson_number=state.lesson_number,
        lesson_title=state.lesson_title,
        lesson_slug=state.lesson_slug,
        processed_date=processed_date or date.today(),
        source_slide_filename=state.source_slide_filename,
        source_transcript_filename=state.transcript.source_filename if state.transcript else None,
        source_transcript_path=state.source_transcript_path,
        source_transcript_binding=state.source_transcript_binding,
        fact_check_passed=state.fact_check_passed,
        has_pending_review=state.has_pending_review,
        removed_unsupported_claims=state.removed_unsupported_claims,
        body_markdown=final_body,
        extracted_zettels=state.extracted_zettels,
        audit_items=state.audit_items,
        cross_links=state.cross_links,
        detected_tensions=state.detected_tensions,
    )
    state.output = output
    return state


def execute_pipeline(
    state: LessonPipelineState,
    client: StructuredLLMClient,
    auditor_client: StructuredLLMClient | None = None,
    processed_date: date | None = None,
    humanizer_max_attempts: int = 3,
    allow_pending_review: bool = False,
) -> LessonPipelineState:
    """Executes the full linear pipeline graph across drafting, auditing, and humanizing.

    Transitions LessonPipelineState through draft_node, fact_check_node,
    humanize_node, and finalize_output_node.

    Args:
        state: Initial LessonPipelineState with slides and syllabus.
        client: Structured LLM client implementation conforming to protocol.
        auditor_client: Optional specialized StructuredLLMClient for the factual auditor.
        processed_date: Optional execution date for output stamping.
        humanizer_max_attempts: Maximum permitted retry attempts for stylistic linter.

    Returns:
        Updated LessonPipelineState containing full execution artifacts and WikiLessonOutput.

    Raises:
        HumanizerValidationError: If humanizer output fails linter after max attempts.
        Exception: If any pipeline node encounters an unhandled runtime error.
    """
    # 1. Redação Híbrida Wiki + Zettel
    state = draft_node(state=state, client=client)

    # 2. Auditoria Factual Adversarial
    state = fact_check_node(
        state=state,
        client=auditor_client or client,
        allow_pending_review=allow_pending_review,
    )
    state.audit_items = [
        item.model_copy(update={"audit_stage": "draft"}) for item in state.audit_items
    ]
    if not state.fact_check_passed:
        raise FactCheckBlockedError(state)

    # 3. Polimento Estilístico com Validação e Retentativa
    state = humanize_node(state=state, client=client, max_attempts=humanizer_max_attempts)

    # 4. Audit the exact post-humanizer artifacts via invariance check against audited prose.
    state.fact_check_passed = False
    final_audit = audit_humanized_invariance(
        audited_markdown=state.audited_markdown or "",
        humanized_markdown=state.humanized_markdown or "",
        client=auditor_client or client,
        zettels=[zettel.model_copy(deep=True) for zettel in state.extracted_zettels],
        tensions=[tension.model_copy(deep=True) for tension in state.detected_tensions],
        allow_pending_review=allow_pending_review,
    )
    state.audit_items.extend(
        item.model_copy(update={"audit_stage": "final"}) for item in final_audit.audit_items
    )
    if not final_audit.fact_check_passed or (
        not allow_pending_review
        and any(
            item.verdict != "verified" or (item.severity is not None and item.severity != "S6")
            for item in final_audit.audit_items
        )
    ):
        raise FactCheckBlockedError(state)
    state.fact_check_passed = True
    state.has_pending_review = state.has_pending_review or final_audit.has_pending_review

    # 5. Finalização e Construção do Contrato de Saída
    state = finalize_output_node(state=state, processed_date=processed_date)

    return state


def run_lesson_pipeline(
    state: LessonPipelineState,
    client: StructuredLLMClient,
    auditor_client: StructuredLLMClient | None = None,
    processed_date: date | None = None,
    humanizer_max_attempts: int = 3,
    allow_pending_review: bool = False,
) -> WikiLessonOutput:
    """Executes the pipeline graph and returns the finalized WikiLessonOutput.

    Args:
        state: Initial LessonPipelineState with slides and syllabus.
        client: Structured LLM client implementation.
        auditor_client: Optional specialized StructuredLLMClient for the factual auditor.
        processed_date: Optional processing date. Defaults to date.today().
        humanizer_max_attempts: Maximum retry count for humanizer convergence.

    Returns:
        Validated WikiLessonOutput ready for vault export.

    Raises:
        HumanizerValidationError: If stylistic validation cannot converge.
        RuntimeError: If output was not successfully constructed.
    """
    final_state = execute_pipeline(
        state=state,
        client=client,
        auditor_client=auditor_client,
        processed_date=processed_date,
        humanizer_max_attempts=humanizer_max_attempts,
        allow_pending_review=allow_pending_review,
    )
    if final_state.output is None:
        raise RuntimeError("Pipeline completed execution but failed to produce WikiLessonOutput.")
    return final_state.output


__all__ = [
    "create_initial_state",
    "execute_pipeline",
    "finalize_output_node",
    "find_syllabus_module",
    "ingestion_node",
    "run_lesson_pipeline",
    "slugify",
]
