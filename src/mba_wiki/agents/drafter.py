"""Drafter and decomposition agent node for academic wiki lesson processing.

Anchors extracted slide chunks against the official course syllabus, expands
concise slide topics into comprehensive textbook-style chapter prose, and extracts
candidate universal concepts as AtomicZettel notes for the Zettelkasten.
"""

from pathlib import Path

from mba_wiki.agents.llm_client import StructuredLLMClient
from mba_wiki.schemas import (
    DraftResult,
    LessonPipelineState,
    SlideChunk,
    StructuredSyllabus,
    SyllabusModule,
)

DEFAULT_DRAFTER_PROMPT_PATH = Path(__file__).parent / "prompts" / "drafter.md"


def get_drafter_prompt(prompt_path: Path | None = None) -> str:
    """Loads the drafter system prompt dynamically from an external markdown file.

    Args:
        prompt_path: Optional explicit path to prompt file. Defaults to DEFAULT_DRAFTER_PROMPT_PATH.

    Returns:
        String content of the drafter prompt markdown file.

    Raises:
        FileNotFoundError: If the specified prompt file cannot be found on disk.
    """
    resolved_path = prompt_path or DEFAULT_DRAFTER_PROMPT_PATH
    if not resolved_path.is_file():
        raise FileNotFoundError(f"Drafter system prompt file not found: {resolved_path}")
    return resolved_path.read_text(encoding="utf-8")


def format_drafter_user_prompt(
    slides: list[SlideChunk],
    syllabus: SyllabusModule,
    full_syllabus: StructuredSyllabus | None = None,
    lesson_title: str | None = None,
) -> str:
    """Formats contextual input payload containing syllabus guidelines and slide chunks.

    Args:
        slides: Ordered list of slide chunks extracted from the lesson presentation.
        syllabus: Anchoring syllabus module containing scope, topics, and bibliography.
        full_syllabus: Optional full course curriculum for cross-disciplinary insights.
        lesson_title: Optional title of the lesson theme being drafted.

    Returns:
        Formatted markdown string representing the user prompt for the LLM.

    Raises:
        None.
    """
    sections: list[str] = []

    # 1. Lesson Header
    if lesson_title:
        sections.append(f"# Tema da Aula: {lesson_title}\n")

    # 2. Syllabus Anchoring Context
    topics_list = "\n".join(f"- {t}" for t in syllabus.topics)
    bib_list = "\n".join(f"- {b}" for b in syllabus.bibliography)
    prof_info = f"\nProfessor(a): {syllabus.professor}" if syllabus.professor else ""

    syllabus_context = (
        f"## Diretrizes Curriculares da Disciplina\n"
        f"Disciplina: {syllabus.discipline_name} "
        f"(slug: `{syllabus.discipline_slug}`){prof_info}\n\n"
        f"### Ementa e Objetivos\n{syllabus.syllabus_summary}\n\n"
        f"### Tópicos Oficiais da Matéria\n{topics_list}\n\n"
        f"### Bibliografia Recomendada\n{bib_list}"
    )
    sections.append(syllabus_context)

    # 3. Global Curriculum Context (Cross-Discipline Insights)
    if full_syllabus and full_syllabus.modules:
        curriculum_lines: list[str] = [
            "## Visão Global do Currículo do MBA (Conexões Interdisciplinares)\n"
            "Abaixo estão os módulos curriculares do MBA com seus tópicos chave. "
            "Utilize esta visão sistêmica para identificar conexões transversais "
            "(`cross_links`) e dilemas gerenciais dialéticos (`detected_tensions`):\n"
        ]
        for module in full_syllabus.modules:
            topics_summary = ", ".join(module.topics) if module.topics else "Geral"
            prefix = (
                "*(Disciplina Atual)* "
                if module.discipline_slug == syllabus.discipline_slug
                else ""
            )
            curriculum_lines.append(
                f"- {prefix}**{module.discipline_name}** "
                f"(`{module.discipline_slug}`): {topics_summary}"
            )
        sections.append("\n".join(curriculum_lines))

    # 4. Slide Content Payloads
    slides_context_parts: list[str] = ["## Conteúdo Bruto Extraído dos Slides"]
    for chunk in slides:
        slide_header = f"### Slide {chunk.slide_number}: {chunk.title}"
        body_text = chunk.raw_text.strip()

        eqs_text = ""
        if chunk.latex_equations:
            eqs_list = "\n".join(f"- $${eq}$$" for eq in chunk.latex_equations)
            eqs_text = f"\nFórmulas LaTeX detectadas:\n{eqs_list}"

        visuals_text = ""
        if chunk.visual_descriptions:
            vis_list = "\n".join(f"- {v}" for v in chunk.visual_descriptions)
            visuals_text = f"\nElementos visuais:\n{vis_list}"

        slide_block = f"{slide_header}\n{body_text}{eqs_text}{visuals_text}"
        slides_context_parts.append(slide_block)

    sections.append("\n\n".join(slides_context_parts))
    return "\n\n".join(sections)


def generate_draft(
    slides: list[SlideChunk],
    syllabus: SyllabusModule,
    client: StructuredLLMClient,
    full_syllabus: StructuredSyllabus | None = None,
    lesson_title: str | None = None,
    prompt: str | None = None,
) -> DraftResult:
    """Executes structured generation to produce the lesson draft and atomic zettels.

    Args:
        slides: Ordered list of slide chunks to expand.
        syllabus: Anchoring syllabus module for the discipline.
        client: Implementation conforming to StructuredLLMClient protocol.
        full_syllabus: Optional full course curriculum for cross-disciplinary insights.
        lesson_title: Optional human-readable lesson theme title.
        prompt: Optional system prompt override. Defaults to loaded drafter prompt.

    Returns:
        DraftResult containing raw_draft, extracted_zettels, cross_links, and detected_tensions.

    Raises:
        ValueError: If slides list is empty.
        Exception: If structured generation fails.
    """
    if not slides:
        raise ValueError("Cannot draft lesson with empty slide list.")

    system_prompt = prompt or get_drafter_prompt()
    user_prompt = format_drafter_user_prompt(
        slides=slides,
        syllabus=syllabus,
        full_syllabus=full_syllabus,
        lesson_title=lesson_title,
    )

    result: DraftResult = client.generate_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_model=DraftResult,
    )
    return result


def draft_node(
    state: LessonPipelineState,
    client: StructuredLLMClient,
) -> LessonPipelineState:
    """Graph node executor for the drafting stage within the lesson pipeline.

    Receives the current LessonPipelineState, invokes the drafting agent with the
    state's slides, syllabus, and optional full_syllabus, and populates raw_draft,
    extracted_zettels, cross_links, and detected_tensions.

    Args:
        state: Current pipeline state before drafting.
        client: Structured LLM client implementation.

    Returns:
        Updated LessonPipelineState containing generated draft and candidate zettels.

    Raises:
        ValueError: If state does not contain slides.
        Exception: If draft generation fails.
    """
    draft_result = generate_draft(
        slides=state.slides,
        syllabus=state.syllabus,
        client=client,
        full_syllabus=state.full_syllabus,
        lesson_title=state.lesson_title,
    )

    state.raw_draft = draft_result.raw_draft
    state.extracted_zettels = list(draft_result.extracted_zettels)
    state.cross_links = list(draft_result.cross_links)
    state.detected_tensions = list(draft_result.detected_tensions)
    return state


__all__ = [
    "DEFAULT_DRAFTER_PROMPT_PATH",
    "draft_node",
    "format_drafter_user_prompt",
    "generate_draft",
    "get_drafter_prompt",
]
