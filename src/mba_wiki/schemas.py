"""Data contracts and Pydantic v2 schemas for the MBA Wiki Engine.

Defines schemas for course syllabi, slide chunks, factual auditing, atomic
zettels, wiki lessons, and the end-to-end pipeline state machine.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class SyllabusModule(BaseModel):
    """Schema representing an academic discipline module from the course syllabus.

    Attributes:
        discipline_slug: URL-friendly identifier for the discipline.
        discipline_name: Official name of the course or discipline.
        professor: Name of the lecturing professor, if available.
        syllabus_summary: Executive summary of module objectives and scope.
        topics: List of key topics covered throughout the course module.
        bibliography: Official references and recommended readings.
    """

    discipline_slug: str
    discipline_name: str
    professor: str | None = None
    syllabus_summary: str
    topics: list[str]
    bibliography: list[str]


class StructuredSyllabus(BaseModel):
    """Schema representing the full course curriculum containing multiple modules.

    Attributes:
        modules: List of syllabus modules composing the MBA program.
    """

    modules: list[SyllabusModule]


class SlideChunk(BaseModel):
    """Schema representing content extracted from an individual presentation slide.

    Attributes:
        slide_number: Sequential 1-based index of the slide.
        title: Extracted slide header or inferred title.
        raw_text: Raw plain text content extracted from the slide.
        latex_equations: List of mathematical formulas isolated in LaTeX format.
        visual_descriptions: Descriptive representations of diagrams, charts, or images.
    """

    slide_number: int
    title: str
    raw_text: str
    latex_equations: list[str] = Field(default_factory=list)
    visual_descriptions: list[str] = Field(default_factory=list)


class ClaimAuditItem(BaseModel):
    """Schema representing an audited factual claim extracted from lesson prose.

    Attributes:
        claim_id: Unique identifier for the audited statement.
        quote: Exact sentence or excerpt analyzed from the draft text.
        category: Domain classification of the claim.
        verdict: Fact-checking determination for the claim.
        severity: Severity code (S1 to S6) if an issue is detected.
        evidence_source: Slide citation or external source validating the claim.
        proposed_fix: Suggested correction for false or imprecise statements.
    """

    claim_id: str
    quote: str
    category: Literal["formula", "date", "attribution", "technical", "metric"]
    verdict: Literal["verified", "false", "imprecise", "misleading", "unsupported"]
    severity: Literal["S1", "S2", "S3", "S4", "S5", "S6"] | None = None
    evidence_source: str | None = None
    proposed_fix: str | None = None


class AtomicZettel(BaseModel):
    """Schema representing an atomic conceptual note destined for the Zettelkasten.

    Attributes:
        slug: Normalized identifier used for the Markdown filename and links.
        title: Human-readable concept title.
        domain_tags: List of categorization tags for knowledge indexing.
        content_markdown: Self-contained conceptual note body in Markdown.
        related_links: List of slugs pointing to related conceptual notes.
    """

    slug: str
    title: str
    domain_tags: list[str]
    content_markdown: str
    related_links: list[str]


class WikiLessonOutput(BaseModel):
    """Schema representing the completed, audited, and humanized wiki lesson output.

    Attributes:
        discipline_slug: Identifier of the associated discipline.
        discipline_name: Human-readable name of the discipline.
        lesson_number: Sequential lesson number within the discipline.
        lesson_title: Descriptive title of the lesson theme.
        lesson_slug: Slug identifier for the lesson file.
        processed_date: Date when the lesson was processed by the pipeline.
        source_slide_filename: Filename of the source presentation.
        fact_check_passed: Indicates whether factual auditing passed without blockers.
        removed_unsupported_claims: Number of ungrounded statements pruned.
        body_markdown: Final sanitized and humanized lesson chapter text.
        extracted_zettels: Atomic conceptual notes derived from this lesson.
        audit_items: Complete record of claims audited during processing.
    """

    discipline_slug: str
    discipline_name: str
    lesson_number: int
    lesson_title: str
    lesson_slug: str
    processed_date: date
    source_slide_filename: str
    fact_check_passed: bool
    removed_unsupported_claims: int
    body_markdown: str
    extracted_zettels: list[AtomicZettel]
    audit_items: list[ClaimAuditItem] = Field(default_factory=list)


class LessonAuditReport(BaseModel):
    """Schema representing the standalone factual audit report persisted to disk.

    Attributes:
        discipline_slug: Identifier of the associated discipline.
        discipline_name: Human-readable name of the discipline.
        lesson_number: Sequential lesson number within the discipline.
        lesson_title: Descriptive title of the lesson theme.
        processed_date: Date when the audit was performed.
        fact_check_passed: Boolean indicating overall audit pass status.
        total_claims_audited: Total number of claims extracted and evaluated.
        removed_unsupported_claims: Number of S4 claims purged from the output.
        audit_items: Granular records of all evaluated claims.
    """

    discipline_slug: str
    discipline_name: str
    lesson_number: int
    lesson_title: str
    processed_date: date
    fact_check_passed: bool
    total_claims_audited: int
    removed_unsupported_claims: int
    audit_items: list[ClaimAuditItem] = Field(default_factory=list)


class LessonPipelineState(BaseModel):
    """Schema representing the execution state passed between pipeline nodes.

    Attributes:
        discipline_slug: Identifier of the associated discipline.
        discipline_name: Human-readable name of the discipline.
        lesson_number: Sequential lesson number within the discipline.
        lesson_title: Descriptive title of the lesson theme.
        lesson_slug: Slug identifier for the lesson file.
        source_slide_filename: Filename of the source presentation.
        slides: Ordered list of slide chunks extracted from the file.
        syllabus: Anchoring syllabus module for the current discipline.
        raw_draft: Preliminary lesson draft generated by the drafting node.
        extracted_zettels: Candidate atomic notes identified during drafting.
        audit_items: Factual audit verdicts recorded by the auditor node.
        fact_check_passed: Boolean flag indicating factual integrity.
        removed_unsupported_claims: Count of removed unsupported claims.
        audited_markdown: Draft text after factual pruning and corrections.
        humanized_markdown: Polished text adhering to stylistic linter rules.
        humanizer_retry_count: Number of humanizer remediation attempts made.
        output: Finalized WikiLessonOutput ready for persistence.
    """

    discipline_slug: str
    discipline_name: str
    lesson_number: int
    lesson_title: str
    lesson_slug: str
    source_slide_filename: str
    slides: list[SlideChunk]
    syllabus: SyllabusModule
    raw_draft: str | None = None
    extracted_zettels: list[AtomicZettel] = Field(default_factory=list)
    audit_items: list[ClaimAuditItem] = Field(default_factory=list)
    fact_check_passed: bool = False
    removed_unsupported_claims: int = 0
    audited_markdown: str | None = None
    humanized_markdown: str | None = None
    humanizer_retry_count: int = 0
    output: WikiLessonOutput | None = None


__all__ = [
    "AtomicZettel",
    "ClaimAuditItem",
    "LessonAuditReport",
    "LessonPipelineState",
    "SlideChunk",
    "StructuredSyllabus",
    "SyllabusModule",
    "WikiLessonOutput",
]
