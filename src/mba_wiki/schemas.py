"""Data contracts and Pydantic v2 schemas for the MBA Wiki Engine.

Defines schemas for course syllabi, slide chunks, factual auditing, atomic
zettels, wiki lessons, and the end-to-end pipeline state machine.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


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


class AuditClaimsResponse(BaseModel):
    """Schema representing the collection of audited factual statements from the LLM.

    Attributes:
        claims: List of individual factual statements analyzed with verdicts and severities.
    """

    claims: list[ClaimAuditItem] = Field(default_factory=list)


class HumanizerResult(BaseModel):
    """Schema representing the outcome of stylistic rewriting and validation.

    Attributes:
        humanized_text: Stylistically polished prose text adhering to linter rules.
        retry_count: Total number of generation and remediation attempts made.
        is_valid: Boolean indicating whether deterministic linter validation passed.
    """

    humanized_text: str
    retry_count: int
    is_valid: bool


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


class CrossDisciplineLink(BaseModel):
    """Schema representing a cross-disciplinary conceptual bridge between MBA subjects.

    Attributes:
        target_discipline_slug: Slug identifier of the target or impacted discipline.
        target_topic: Specific topic or concept within the target discipline.
        connection_type: Nature of semantic link (prerequisite, impact, contrast, synergy).
        description: Synthetic narrative explaining the practical or theoretical interface.
    """

    target_discipline_slug: str
    target_topic: str
    connection_type: Literal["prerequisite", "impact", "contrast", "synergy"]
    description: str


class DialecticalTension(BaseModel):
    """Schema representing an executive dilemma or dialectical tension across models.

    Attributes:
        slug: Normalized identifier for the tension file and linking.
        title: Human-readable descriptive title of the conflict/polarity.
        pole_a_discipline: Slug or name of discipline anchoring thesis A.
        pole_a_framework: Name of framework, model, or theory in Pole A.
        pole_a_thesis: Central assertion or optimization goal of Pole A.
        pole_b_discipline: Slug or name of discipline anchoring antithesis B.
        pole_b_framework: Name of framework, model, or theory in Pole B.
        pole_b_thesis: Central assertion or optimization goal of Pole B.
        tension_nature: Fundamental trade-off (e.g., Short-term vs Long-term, Cost vs Agility).
        synthesis_guidelines: Managerial criteria or boundary conditions for practical synthesis.
        related_zettel_slugs: Associated atomic zettel identifiers.
    """

    slug: str
    title: str
    pole_a_discipline: str
    pole_a_framework: str
    pole_a_thesis: str
    pole_b_discipline: str
    pole_b_framework: str
    pole_b_thesis: str
    tension_nature: str
    synthesis_guidelines: str
    related_zettel_slugs: list[str] = Field(default_factory=list)


class FactCheckResult(BaseModel):
    """Schema representing the consolidated factual audit outcome and text remediation.

    Attributes:
        audit_items: Complete record of all individual claims audited.
        fact_check_passed: Boolean indicating whether factual auditing passed without blockers.
        removed_unsupported_claims: Total count of ungrounded statements pruned from the text.
        audited_markdown: The final sanitized and remediated draft prose.
        validated_zettels: Factually audited and validated atomic zettel notes.
        validated_tensions: Factually audited and validated dialectical tensions.
    """

    audit_items: list[ClaimAuditItem] = Field(default_factory=list)
    fact_check_passed: bool
    removed_unsupported_claims: int = 0
    audited_markdown: str
    validated_zettels: list[AtomicZettel] = Field(default_factory=list)
    validated_tensions: list[DialecticalTension] = Field(default_factory=list)


class DraftResult(BaseModel):
    """Schema representing the preliminary draft, candidate zettels, links, and tensions.

    Attributes:
        raw_draft: Preliminary expanded lesson chapter text in Markdown.
        extracted_zettels: Candidate universal concepts identified for the Zettelkasten.
        cross_links: Cross-disciplinary linkages to topics in other course modules.
        detected_tensions: Dialectical tensions and trade-offs surfaced in this lesson.
    """

    raw_draft: str
    extracted_zettels: list[AtomicZettel] = Field(default_factory=list)
    cross_links: list[CrossDisciplineLink] = Field(default_factory=list)
    detected_tensions: list[DialecticalTension] = Field(default_factory=list)


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
        source_transcript_filename: Optional filename of the recorded lecture transcript.
        fact_check_passed: Indicates whether factual auditing passed without blockers.
        removed_unsupported_claims: Number of ungrounded statements pruned.
        body_markdown: Final sanitized and humanized lesson chapter text.
        extracted_zettels: Atomic conceptual notes derived from this lesson.
        audit_items: Complete record of claims audited during processing.
        cross_links: Cross-disciplinary linkages identified during drafting.
        detected_tensions: Dialectical tensions identified during drafting.
    """

    discipline_slug: str
    discipline_name: str
    lesson_number: int
    lesson_title: str
    lesson_slug: str
    processed_date: date
    source_slide_filename: str
    source_transcript_filename: str | None = None
    fact_check_passed: bool
    removed_unsupported_claims: int
    body_markdown: str
    extracted_zettels: list[AtomicZettel]
    audit_items: list[ClaimAuditItem] = Field(default_factory=list)
    cross_links: list[CrossDisciplineLink] = Field(default_factory=list)
    detected_tensions: list[DialecticalTension] = Field(default_factory=list)


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


class TranscriptSegment(BaseModel):
    """Schema representing a time-delimited spoken audio segment.

    Attributes:
        id: Sequential identifier of the segment.
        start: Starting timestamp of the segment in seconds.
        end: Ending timestamp of the segment in seconds.
        text_raw: Literal spoken transcript produced by the transcription engine.
        text_cleaned: Sanitized transcript with speech disfluencies and fillers removed.
    """

    id: int
    start: float = Field(..., ge=0.0, description="Starting timestamp in seconds")
    end: float = Field(..., ge=0.0, description="Ending timestamp in seconds")
    text_raw: str = Field(..., description="Literal transcribed text")
    text_cleaned: str = Field(..., description="Cleaned transcript without speech disfluencies")

    @model_validator(mode="after")
    def validate_timestamp_interval(self) -> "TranscriptSegment":
        """Validates that the ending timestamp is not earlier than the start timestamp.

        Returns:
            TranscriptSegment: Self if interval is valid.

        Raises:
            ValueError: If end timestamp is strictly less than start timestamp.
        """
        if self.end < self.start:
            raise ValueError(f"End timestamp ({self.end}) cannot be less than start ({self.start})")
        return self


class VideoTranscript(BaseModel):
    """Schema representing the consolidated transcript artifact of a recorded lecture.

    Attributes:
        source_filename: Name of the original source video file.
        discipline_slug: Identifier for the corresponding academic discipline.
        duration_seconds: Total duration of the recorded video in seconds.
        model_name: Transcription model used for inference.
        compute_type: Computation and quantization precision used during inference.
        processed_at: Timestamp when transcription was completed.
        full_text_raw: Unfiltered concatenated text of all spoken segments.
        full_text_cleaned: Concatenated cleaned text with conversational fillers purged.
        segments: Ordered collection of individual transcript segments.
    """

    source_filename: str
    discipline_slug: str
    duration_seconds: float = Field(..., ge=0.0, description="Total video duration in seconds")
    model_name: str
    compute_type: str
    processed_at: datetime
    full_text_raw: str
    full_text_cleaned: str
    segments: list[TranscriptSegment] = Field(default_factory=list)


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
        transcript: Optional consolidated speech transcript of the recorded lecture.
        syllabus: Anchoring syllabus module for the current discipline.
        full_syllabus: Optional full course curriculum for cross-disciplinary insights.
        raw_draft: Preliminary lesson draft generated by the drafting node.
        extracted_zettels: Candidate atomic notes identified during drafting.
        audit_items: Factual audit verdicts recorded by the auditor node.
        fact_check_passed: Boolean flag indicating factual integrity.
        removed_unsupported_claims: Count of removed unsupported claims.
        audited_markdown: Draft text after factual pruning and corrections.
        humanized_markdown: Polished text adhering to stylistic linter rules.
        humanizer_retry_count: Number of humanizer remediation attempts made.
        output: Finalized WikiLessonOutput ready for persistence.
        cross_links: Cross-disciplinary linkages identified during drafting.
        detected_tensions: Dialectical tensions identified during drafting.
    """

    discipline_slug: str
    discipline_name: str
    lesson_number: int
    lesson_title: str
    lesson_slug: str
    source_slide_filename: str
    slides: list[SlideChunk]
    transcript: VideoTranscript | None = None
    syllabus: SyllabusModule
    full_syllabus: StructuredSyllabus | None = None
    raw_draft: str | None = None
    extracted_zettels: list[AtomicZettel] = Field(default_factory=list)
    audit_items: list[ClaimAuditItem] = Field(default_factory=list)
    fact_check_passed: bool = False
    removed_unsupported_claims: int = 0
    audited_markdown: str | None = None
    humanized_markdown: str | None = None
    humanizer_retry_count: int = 0
    output: WikiLessonOutput | None = None
    cross_links: list[CrossDisciplineLink] = Field(default_factory=list)
    detected_tensions: list[DialecticalTension] = Field(default_factory=list)


__all__ = [
    "AtomicZettel",
    "AuditClaimsResponse",
    "ClaimAuditItem",
    "CrossDisciplineLink",
    "DialecticalTension",
    "DraftResult",
    "FactCheckResult",
    "HumanizerResult",
    "LessonAuditReport",
    "LessonPipelineState",
    "SlideChunk",
    "StructuredSyllabus",
    "SyllabusModule",
    "TranscriptSegment",
    "VideoTranscript",
    "WikiLessonOutput",
]
