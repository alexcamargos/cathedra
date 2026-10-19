"""Stylistic humanizer agent node with deterministic validation and retry loop.

Polishes expanded academic prose by enforcing natural sentence structures, removing
mechanical AI clichés, and validating outputs against validators.py with a retry
loop allowing up to 3 self-correction attempts.
"""

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

        current_candidate = client.generate_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.3,
        ).strip()

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
    within the retry loop, and updates state with polished prose and retry metrics.

    Args:
        state: Pipeline state containing audited markdown.
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
    return state


__all__ = [
    "DEFAULT_HUMANIZER_PROMPT_PATH",
    "HumanizerValidationError",
    "format_remediation_feedback",
    "get_humanizer_prompt",
    "humanize_node",
    "humanize_text",
]
