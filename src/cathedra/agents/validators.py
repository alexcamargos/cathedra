"""Deterministic prose linter for academic style and mechanical guidelines.

Inspects markdown prose blocks to enforce typography rules, punctuation standards,
paragraph length limits, and strict lexical blacklists according to docs/LINTER_RULES.md.
"""

import re
from dataclasses import dataclass, field

# Rule R1: Prohibited explanatory dashes (em-dash and en-dash)
RE_PROHIBITED_DASHES = re.compile(r"[—–]")

# Rule R2: Prohibited decorative symbols and emojis
RE_DECORATIVE_ARROWS = re.compile(r"[→⇒←⇐↔↕↗↘↖↙]")
RE_EMOJIS = re.compile(r"[\U0001F300-\U0001FAFF]|[\U00002600-\U000027BF]")

# Rule R4: Prohibited mechanical bullet list pattern
RE_AI_BULLET_PATTERN = re.compile(r"^\s*[-*]\s+\*\*[^*]+(?::\*\*|\*\*:\s*)", re.MULTILINE)

# Common abbreviations and tokens that should not trigger sentence boundary splits
RE_ABBREVIATIONS = re.compile(
    r"\b(?:ex|i\.e|e\.g|dr|dra|prof|profa|et\s+al|vs|art|sr|sra|v\.g|p|pp|vol|cap|ed|seç|sec|n|no|fig)\.",
    re.IGNORECASE,
)
RE_DECIMAL_POINTS = re.compile(r"(?<=\d)\.(?=\d)")
RE_ELLIPSES = re.compile(r"\.{3,}")

# Section 3: Lexical Blacklist Patterns (Case-insensitive)
LEXICAL_BLACKLIST: list[tuple[str, str, list[str]]] = [
    (
        "L1_AI_OPENER",
        "Expressão clichê de abertura de IA proibida.",
        [
            r"\bno cenário atual\b",
            r"\bno mundo dinâmico de hoje\b",
            r"\bna era da informação\b",
            r"\bnão é segredo que\b",
            r"\bvamos mergulhar\b",
            r"\bvamos examinar\b",
        ],
    ),
    (
        "L2_EMPTY_APHORISM",
        "Aforismo oco ou contraste vazio de IA proibido.",
        [
            r"\bno seu cerne\b",
            r"\ba verdadeira questão é\b",
            r"\bo que realmente importa é\b",
            r"\bna essência\b",
            r"\bnão é apenas sobre\b",
            r"\bmais do que\b",
        ],
    ),
    (
        "L3_METAPHOR",
        "Metáfora gasta ou verbo figurado proibido.",
        [
            r"\bmergulho profundo\b",
            r"\bdesbloquear o potencial\b",
            r"\bnavegar pelo cenário\b",
            r"\bfaca de dois gumes\b",
            r"\btapeçaria\b",
            r"\bmosaico\b",
            r"\bsinfonia\b",
            r"\bvirada de chave\b",
            r"\bgame changer\b",
            r"\balavancar\b",
            r"\bfomentar\b",
            r"\bpotencializar\b",
        ],
    ),
    (
        "L4_HISTRIONIC_ADJECTIVE",
        "Adjetivo histriônico proibido no texto acadêmico.",
        [
            r"\bcrucia(?:l|is)\b",
            r"\bfundamenta(?:l|is)\b",
            r"\bpivota(?:l|is)\b",
            r"\brevolucionári[oas]+\b",
            r"\bfascinante[s]?\b",
            r"\bincríve(?:l|is)\b",
            r"\bimprescindíve(?:l|is)\b",
            r"\bdisruptiv[oas]+\b",
        ],
    ),
    (
        "L5_STIFF_CONNECTIVE",
        "Conectivo engessado proibido.",
        [
            r"\boutrossim\b",
            r"\bademais\b",
            r"\bdestarte\b",
            r"\bpor conseguinte\b",
            r"\bvale ressaltar que\b",
            r"\bé importante notar que\b",
            r"\bcabe destacar\b",
        ],
    ),
    (
        "L6_AI_CLOSING",
        "Fechamento otimista clichê de IA proibido.",
        [
            r"\bem suma\b",
            r"\bem resumo\b",
            r"\bconcluindo\b",
            r"\bo futuro parece promissor\b",
            r"\btempos empolgantes estão por vir\b",
        ],
    ),
    (
        "L7_ASSISTANT_RESIDUE",
        "Resíduo conversacional de assistente proibido.",
        [
            r"\bespero que ajude\b",
            r"\bcom certeza\b",
            r"\bexcelente pergunta\b",
            r"\bcomo uma ia\b",
            r"\bcomo modelo de linguagem\b",
        ],
    ),
]


@dataclass(frozen=True)
class LinterViolation:
    """Represents a specific stylistic or mechanical linter violation.

    Attributes:
        rule_id: Unique identifier for the violated rule (e.g. 'R1_DASH', 'L1_AI_OPENER').
        message: Human-friendly explanation explaining the error for LLM feedback.
        line_number: 1-based line number where the violation was detected, if available.
        matched_text: The offending text snippet or term triggering the violation.
    """

    rule_id: str
    message: str
    line_number: int | None = None
    matched_text: str | None = None


@dataclass
class ValidationResult:
    """Overall outcome of validating a markdown prose segment.

    Attributes:
        is_valid: True if zero violations were detected, False otherwise.
        violations: List of all detected LinterViolation items.
    """

    is_valid: bool
    violations: list[LinterViolation] = field(default_factory=list)


def mask_ignored_elements(text: str) -> str:
    """Masks code blocks, inline code, LaTeX math, and HTML comments.

    Replaces non-newline characters within technical blocks with whitespace, preserving
    exact string lengths, line breaks, and line numbers for subsequent inspections.

    Args:
        text: Raw markdown prose string to be masked.

    Returns:
        Masked markdown string with technical syntax replaced by spaces.

    Raises:
        None.
    """

    def blank_match(match: re.Match[str]) -> str:
        """Blanks matched content replacing everything except newlines with spaces.

        Args:
            match: Regex match object.

        Returns:
            String of equal length containing spaces and preserved newlines.

        Raises:
            None.
        """
        content = match.group(0)
        return "".join("\n" if char == "\n" else " " for char in content)

    # 1. HTML comments: <!-- ... -->
    masked = re.sub(r"<!--[\s\S]*?-->", blank_match, text)

    # 2. Fenced code blocks: ```...``` or ~~~...~~~
    masked = re.sub(r"```[\s\S]*?```", blank_match, masked)
    masked = re.sub(r"~~~[\s\S]*?~~~", blank_match, masked)

    # 3. LaTeX display math: $$...$$
    masked = re.sub(r"\$\$[\s\S]*?\$\$", blank_match, masked)

    # 4. Inline code: `...`
    masked = re.sub(r"`[^`\n]+`", blank_match, masked)

    # 5. Inline LaTeX math: $...$
    masked = re.sub(r"(?<!\$)\$(?!\$)[^$\n]+(?<!\$)\$(?!\$)", blank_match, masked)

    return masked


def count_sentences(paragraph: str) -> int:
    """Counts the number of sentences in a continuous prose paragraph.

    Filters out common abbreviations, decimal numbers, and ellipses before
    splitting on punctuation marks (., !, ?).

    Args:
        paragraph: Text of an individual paragraph.

    Returns:
        Number of distinct sentences detected.

    Raises:
        None.
    """
    cleaned = RE_ABBREVIATIONS.sub(" ABBR ", paragraph)
    cleaned = RE_DECIMAL_POINTS.sub(",", cleaned)
    cleaned = RE_ELLIPSES.sub(" ", cleaned)

    parts = [s.strip() for s in re.split(r"[.!?]+[\"'\)\]]*(?:\s+|$)", cleaned) if s.strip()]
    return len(parts)


def validate_markdown_prose(text: str) -> ValidationResult:
    """Validates markdown prose against deterministic style and content rules.

    Applies masking to code and LaTeX blocks, checks typography (dashes, emojis,
    symbols), enforces sentence limits per paragraph, inspects mechanical bullet patterns,
    and flags lexical blacklist occurrences.

    Args:
        text: Markdown prose string to inspect.

    Returns:
        ValidationResult indicating validity and enumerating any violations found.

    Raises:
        None.
    """
    masked = mask_ignored_elements(text)
    violations: list[LinterViolation] = []

    # Helper to calculate 1-based line number from string offset
    def get_line_number(offset: int) -> int:
        """Calculates 1-based line number for character offset in original text.

        Args:
            offset: Character index in text.

        Returns:
            1-based line number.

        Raises:
            None.
        """
        return text[:offset].count("\n") + 1

    # Check Rule R1: Prohibited dashes
    for match in RE_PROHIBITED_DASHES.finditer(masked):
        violations.append(
            LinterViolation(
                rule_id="R1_DASH",
                message=(
                    "Travessões explicativos (— ou –) são proibidos. "
                    "Utilize vírgulas, parênteses ou reestruture a oração."
                ),
                line_number=get_line_number(match.start()),
                matched_text=match.group(0),
            )
        )

    # Check Rule R2: Decorative symbols and emojis
    for match in RE_DECORATIVE_ARROWS.finditer(masked):
        violations.append(
            LinterViolation(
                rule_id="R2_SYMBOL",
                message="Setas decorativas são proibidas no texto acadêmico.",
                line_number=get_line_number(match.start()),
                matched_text=match.group(0),
            )
        )

    for match in RE_EMOJIS.finditer(masked):
        violations.append(
            LinterViolation(
                rule_id="R2_SYMBOL",
                message="Emojis são proibidos no texto acadêmico.",
                line_number=get_line_number(match.start()),
                matched_text=match.group(0),
            )
        )

    # Check Rule R4: Prohibited mechanical bullets
    for match in RE_AI_BULLET_PATTERN.finditer(masked):
        violations.append(
            LinterViolation(
                rule_id="R4_AI_BULLET",
                message=(
                    "Listas mecânicas com padrão clichê de IA ('- **Conceito:** explicação') "
                    "são proibidas no corpo da prosa."
                ),
                line_number=get_line_number(match.start()),
                matched_text=match.group(0).strip(),
            )
        )

    # Check Rule R3: Paragraph sentence count
    # Split by two or more newlines to identify paragraphs
    paragraph_matches = list(re.finditer(r"(?:^|\n\n+)([\s\S]+?)(?=\n\n+|$)", masked))
    for p_match in paragraph_matches:
        raw_para = p_match.group(1).strip()
        if not raw_para:
            continue

        lines = [line.strip() for line in raw_para.splitlines() if line.strip()]
        # Skip if all lines are markdown headings (#), blockquotes (>), or table rows (|)
        if all(
            (line.startswith("#") or line.startswith(">") or line.startswith("|")) for line in lines
        ):
            continue

        sentence_count = count_sentences(raw_para)
        if sentence_count > 4:
            snippet = raw_para if len(raw_para) <= 80 else raw_para[:77] + "..."
            violations.append(
                LinterViolation(
                    rule_id="R3_PARAGRAPH_LENGTH",
                    message=(
                        f"Parágrafo com {sentence_count} frases excede "
                        "o teto máximo de 4 frases por parágrafo."
                    ),
                    line_number=get_line_number(p_match.start(1)),
                    matched_text=snippet,
                )
            )

    # Check Section 3: Lexical Blacklist
    for rule_id, message, patterns in LEXICAL_BLACKLIST:
        for pattern_str in patterns:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            for match in pattern.finditer(masked):
                violations.append(
                    LinterViolation(
                        rule_id=rule_id,
                        message=message,
                        line_number=get_line_number(match.start()),
                        matched_text=match.group(0),
                    )
                )

    return ValidationResult(is_valid=len(violations) == 0, violations=violations)


__all__ = [
    "LEXICAL_BLACKLIST",
    "LinterViolation",
    "ValidationResult",
    "count_sentences",
    "mask_ignored_elements",
    "validate_markdown_prose",
]
