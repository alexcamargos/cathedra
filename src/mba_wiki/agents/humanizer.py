"""Stylistic humanizer agent node with deterministic validation and retry loop.

Polishes expanded academic prose by enforcing natural sentence structures, removing
mechanical AI clichés, and validating outputs against validators.py with a retry
loop allowing up to 3 self-correction attempts.
"""

import re
from pathlib import Path

from mba_wiki.agents.llm_client import StructuredLLMClient
from mba_wiki.agents.validators import LinterViolation, validate_markdown_prose
from mba_wiki.schemas import HumanizerResult, LessonPipelineState

DEFAULT_HUMANIZER_PROMPT_PATH = Path(__file__).parent / "prompts" / "humanizer.md"


class HumanizerValidationError(ValueError):
    """Raised when the humanizer agent fails to produce compliant prose within allowed attempts.

    Attributes:
        violations: List of residual LinterViolation items causing rejection.
    """

    def __init__(self, message: str, violations: list[LinterViolation]) -> None:
        """Initializes HumanizerValidationError with message and residual violations.

        Args:
            message: Descriptive error message explaining the failure.
            violations: List of residual LinterViolation items causing rejection.

        Returns:
            None.

        Raises:
            None.
        """
        super().__init__(message)
        self.violations: list[LinterViolation] = violations


def get_humanizer_prompt(prompt_path: Path | None = None) -> str:
    """Loads the humanizer system prompt dynamically from an external markdown file.

    Args:
        prompt_path: Optional explicit path to prompt file.
            Defaults to DEFAULT_HUMANIZER_PROMPT_PATH.

    Returns:
        String content of the humanizer prompt markdown file.

    Raises:
        FileNotFoundError: If the specified prompt file cannot be found on disk.
    """
    resolved_path = prompt_path or DEFAULT_HUMANIZER_PROMPT_PATH
    if not resolved_path.is_file():
        raise FileNotFoundError(f"Humanizer system prompt file not found: {resolved_path}")
    return resolved_path.read_text(encoding="utf-8")


def format_remediation_feedback(
    violations: list[LinterViolation],
    previous_text: str,
) -> str:
    """Formats targeted corrective feedback detailing linter violations for LLM retry.

    Args:
        violations: List of detected stylistic and mechanical linter violations.
        previous_text: Flawed prose generated in the previous iteration.

    Returns:
        Formatted prompt directing the LLM to eliminate specific detected infractions.

    Raises:
        None.
    """
    lines: list[str] = [
        "O texto gerado anteriormente foi inspecionado e REPROVADO pelo validador determinístico.",
        "As seguintes infrações obrigatórias foram identificadas:",
    ]

    for item in violations:
        loc = f" (Linha {item.line_number})" if item.line_number else ""
        match_snippet = f": '{item.matched_text}'" if item.matched_text else ""
        lines.append(f"- [{item.rule_id}]{loc} {item.message}{match_snippet}")

    lines.extend(
        [
            "",
            "Reescreva a prosa abaixo eliminando integralmente TODOS os erros e vícios listados.",
            "Mantenha rigor técnico, todas as fórmulas LaTeX ($$...$$ e $...$) e links [[wiki]]:",
            "",
            f"```markdown\n{previous_text}\n```",
        ]
    )

    return "\n".join(lines)


def strip_markdown_fences(text: str) -> str:
    """Removes outer markdown code fences from LLM responses if present.

    Preserves internal code fences (e.g. ```python ... ```) while stripping outer
    ```markdown ... ``` or ``` wrappers.

    Args:
        text: Raw text string potentially wrapped in ```markdown ... ``` fences.

    Returns:
        Stripped text without outer markdown code fences.

    Raises:
        None.
    """
    clean = text.strip()
    lines = clean.splitlines()
    if len(lines) >= 2 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
        clean = "\n".join(lines[1:-1]).strip()
    elif clean.startswith("```"):
        clean = re.sub(r"^```(?:markdown|md)?\s*\n?", "", clean)
        clean = re.sub(r"\n?\s*```$", "", clean)
    return clean.strip()


def sanitize_markdown_heuristics(text: str) -> str:
    """Deterministically sanitizes common stylistic violations before LLM invocation.

    Applies deterministic transformations to resolve explanatory em-dashes and
    en-dashes, decorative arrows, and stiff formulaic connectives to prevent
    unnecessary LLM round-trips for simple atomic artifacts.

    Args:
        text: Input markdown text potentially containing stylistic violations.

    Returns:
        Sanitized markdown text with mechanical violations resolved.

    Raises:
        None.
    """
    if not text.strip():
        return text

    # Rule R1: Replace em-dash and en-dash used as parenthetical/explanatory dashes with commas
    sanitized = re.sub(r"\s*[—–]\s*", ", ", text)
    # Fix punctuation collisions caused by dash replacement (e.g., ", ," or ", .")
    sanitized = re.sub(r",\s*,+", ",", sanitized)
    sanitized = re.sub(r",\s*\.", ".", sanitized)
    sanitized = re.sub(r",\s*;", ";", sanitized)
    sanitized = re.sub(r",\s*:", ":", sanitized)

    # Rule R2: Replace decorative arrows with standard ASCII directional tokens
    sanitized = re.sub(r"\s*[→⇒]\s*", " -> ", sanitized)
    sanitized = re.sub(r"\s*[←⇐]\s*", " <- ", sanitized)
    sanitized = re.sub(r"\s*[↔↕]\s*", " <-> ", sanitized)

    # Rule L5: Replace stiff connectives where cleanly substitutable
    sanitized = re.sub(r"(?i)\boutrossim,?\s*", "além disso, ", sanitized)
    sanitized = re.sub(r"(?i)\bademais,?\s*", "além disso, ", sanitized)
    sanitized = re.sub(r"(?i)\bdestarte,?\s*", "assim, ", sanitized)
    sanitized = re.sub(r"(?i)\bpor conseguinte,?\s*", "logo, ", sanitized)
    sanitized = re.sub(r"(?i)\bvale ressaltar que\s*", "", sanitized)
    sanitized = re.sub(r"(?i)\bé importante notar que\s*", "", sanitized)
    sanitized = re.sub(r"(?i)\bcabe destacar que\s*", "", sanitized)

    return sanitized


def humanize_text(
    text: str,
    client: StructuredLLMClient,
    max_attempts: int = 3,
    prompt: str | None = None,
) -> HumanizerResult:
    """Rewrites prose using a closed-loop retry mechanism gated by deterministic linter.

    Submits text to the LLM, validates output via validate_markdown_prose, and
    iteratively feeds back violation diagnostics for up to max_attempts.

    Args:
        text: Source prose to be stylistically humanized.
        client: Implementation conforming to StructuredLLMClient protocol.
        max_attempts: Maximum permitted correction retries before raising an error.
        prompt: Optional system prompt override. Defaults to loaded humanizer prompt.

    Returns:
        HumanizerResult containing validated text, attempt count, and valid flag.

    Raises:
        HumanizerValidationError: If prose cannot pass linter within max_attempts.
    """
    system_prompt = prompt or get_humanizer_prompt()
    last_violations: list[LinterViolation] = []
    current_candidate = ""

    for attempt in range(1, max_attempts + 1):
        if attempt == 1:
            user_prompt = (
                f"Reescreva o rascunho de aula a seguir aplicando as diretrizes de estilo:\n\n"
                f"```markdown\n{text}\n```"
            )
        else:
            user_prompt = format_remediation_feedback(
                violations=last_violations,
                previous_text=current_candidate,
            )

        raw_output = client.generate_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.3,
        )
        current_candidate = strip_markdown_fences(raw_output)

        validation = validate_markdown_prose(current_candidate)
        if validation.is_valid:
            return HumanizerResult(
                humanized_text=current_candidate,
                retry_count=attempt,
                is_valid=True,
            )

        last_violations = validation.violations

    raise HumanizerValidationError(
        f"Humanizer exceeded maximum attempts ({max_attempts}) with residual violations.",
        violations=last_violations,
    )


def humanize_node(
    state: LessonPipelineState,
    client: StructuredLLMClient,
    max_attempts: int = 3,
) -> LessonPipelineState:
    """Graph node executor for the stylistic humanizing stage in the lesson pipeline.

    Receives the pipeline state after factual auditing, humanizes the audited markdown
    and the content_markdown of any extracted zettels within the retry loop, and
    updates state with polished prose and retry metrics.

    Args:
        state: Pipeline state containing audited markdown and extracted zettels.
        client: Structured LLM client implementation.
        max_attempts: Maximum retry count for humanizer convergence.

    Returns:
        Updated LessonPipelineState containing humanized prose and retry count.

    Raises:
        HumanizerValidationError: If humanizer convergence fails within allowed attempts.
    """
    text_to_humanize = state.audited_markdown or state.raw_draft or ""
    result = humanize_text(
        text=text_to_humanize,
        client=client,
        max_attempts=max_attempts,
    )

    state.humanized_markdown = result.humanized_text
    state.humanizer_retry_count = result.retry_count

    # Humanize and validate extracted zettels if they contain linter violations
    for zettel in state.extracted_zettels:
        if zettel.content_markdown.strip():
            zettel_validation = validate_markdown_prose(zettel.content_markdown)
            if not zettel_validation.is_valid:
                # Attempt deterministic heuristic sanitization first to prevent N+1 LLM calls
                sanitized_content = sanitize_markdown_heuristics(zettel.content_markdown)
                if validate_markdown_prose(sanitized_content).is_valid:
                    zettel.content_markdown = sanitized_content
                else:
                    zettel_result = humanize_text(
                        text=sanitized_content,
                        client=client,
                        max_attempts=max_attempts,
                    )
                    zettel.content_markdown = zettel_result.humanized_text

    return state


__all__ = [
    "DEFAULT_HUMANIZER_PROMPT_PATH",
    "HumanizerValidationError",
    "format_remediation_feedback",
    "get_humanizer_prompt",
    "humanize_node",
    "humanize_text",
    "sanitize_markdown_heuristics",
    "strip_markdown_fences",
]
