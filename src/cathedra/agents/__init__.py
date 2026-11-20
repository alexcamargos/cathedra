"""Pipeline agents and validation logic package."""

from cathedra.agents.drafter import (
    draft_node,
    format_drafter_user_prompt,
    generate_draft,
    get_drafter_prompt,
)
from cathedra.agents.fact_checker import (
    apply_audit_remediations,
    audit_lesson_draft,
    fact_check_node,
    format_fact_checker_user_prompt,
    get_fact_checker_prompt,
)
from cathedra.agents.graph import (
    create_initial_state,
    execute_pipeline,
    finalize_output_node,
    find_syllabus_module,
    ingestion_node,
    run_lesson_pipeline,
    slugify,
)
from cathedra.agents.humanizer import (
    HumanizerValidationError,
    format_remediation_feedback,
    get_humanizer_prompt,
    humanize_node,
    humanize_text,
)
from cathedra.agents.llm_client import StructuredLLMClient
from cathedra.agents.validators import (
    LinterViolation,
    ValidationResult,
    mask_ignored_elements,
    validate_markdown_prose,
)

__all__ = [
    "HumanizerValidationError",
    "LinterViolation",
    "StructuredLLMClient",
    "ValidationResult",
    "apply_audit_remediations",
    "audit_lesson_draft",
    "create_initial_state",
    "draft_node",
    "execute_pipeline",
    "fact_check_node",
    "finalize_output_node",
    "find_syllabus_module",
    "format_drafter_user_prompt",
    "format_fact_checker_user_prompt",
    "format_remediation_feedback",
    "generate_draft",
    "get_drafter_prompt",
    "get_fact_checker_prompt",
    "get_humanizer_prompt",
    "humanize_node",
    "humanize_text",
    "ingestion_node",
    "mask_ignored_elements",
    "run_lesson_pipeline",
    "slugify",
    "validate_markdown_prose",
]
