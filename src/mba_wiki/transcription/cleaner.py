"""Deterministic speech normalization and discourse disfluency cleaning module.

Sanitizes transcribed lecture speech by purging vocal hesitations, verbal crutches,
and stuttered repetitions while strictly preserving technical vocabulary and formulas.
"""

import re

from mba_wiki.schemas import TranscriptSegment

# Pattern matching repeated short grammatical tokens (articles, prepositions, conjunctions)
_REPEATED_WORDS_REGEX = re.compile(
    r"\b(o|a|os|as|um|uma|uns|umas|de|do|da|dos|das|em|no|na|nos|nas|por|pelo|pela|para|pra|com|que|se|e|mas)\s+\1\b",
    flags=re.IGNORECASE,
)

# Vocal hesitations and filler sounds (including trailing periods/ellipses)
_HESITATIONS_REGEX = re.compile(
    r"(?:,\s*)?\b(?:[eé]\s*\.\.\.|ah+\s*\.\.\.|hum+\s*\.\.\.|[eé]h+|ah+|hu+m+|hã+|ãh*|uhm*)\b(?:\s*\.\.\.)?(?:,\s*)?",
    flags=re.IGNORECASE,
)

# Specific matcher for isolated leading or surrounded É... / Ah... with dots
_ELLIPSIS_HESITATION_REGEX = re.compile(
    r"(?:^|\s+)[eéah]+\s*\.\.\.\s*",
    flags=re.IGNORECASE,
)

# Verbal crutches and colloquial filler phrases
_CRUTCHES_REGEX = re.compile(
    r"(?:,\s*)?\b(?:tipo assim|vamos dizer assim|por assim dizer)(?:,\s*)?",
    flags=re.IGNORECASE,
)

# Tag questions at the end of sentences or clauses (, né?, , tá?)
_TAG_QUESTIONS_REGEX = re.compile(
    r"(?:,\s*)?\b(?:né|tá)\?(?:\s*)",
    flags=re.IGNORECASE,
)


def _capitalize_sentences(text: str) -> str:
    """Ensures the first letter of each sentence is capitalized after cleaning.

    Args:
        text: Input string with potentially lowercased sentence beginnings.

    Returns:
        str: Text with properly capitalized sentence beginnings.

    Raises:
        None.
    """
    if not text:
        return text

    # Capitalize the very first character
    text = text[0].upper() + text[1:] if len(text) > 1 else text.upper()

    # Capitalize after sentence-ending punctuation (. ? !)
    def _cap_match(match: re.Match[str]) -> str:
        punct = match.group(1)
        space = match.group(2)
        char = match.group(3)
        return f"{punct}{space}{char.upper()}"

    return re.sub(r"([.!?])(\s+)([a-zà-ú])", _cap_match, text)


def clean_speech_text(text: str) -> str:
    """Sanitizes raw transcribed lecture speech into clear academic prose.

    Removes verbal hesitations, repeated tokens, and tag questions without altering
    factual claims, metrics, or domain terminology.

    Args:
        text: Raw transcription string.

    Returns:
        str: Cleaned and normalized text.

    Raises:
        None.
    """
    if not text or not text.strip():
        return ""

    cleaned = text

    # 1. Deduplicate repetitive short words (looping to catch triplicates like "o o o")
    while True:
        new_text = _REPEATED_WORDS_REGEX.sub(r"\1", cleaned)
        if new_text == cleaned:
            break
        cleaned = new_text

    # 2. Purge leading/standalone ellipsis hesitations (e.g. "É... ", "Ah... ")
    cleaned = _ELLIPSIS_HESITATION_REGEX.sub(" ", cleaned)

    # 3. Purge vocal hesitations and filler sounds
    cleaned = _HESITATIONS_REGEX.sub(" ", cleaned)

    # 4. Replace tag questions with sentence period or trim if at end
    cleaned = _TAG_QUESTIONS_REGEX.sub(
        lambda m: "." if not m.string.endswith(m.group(0)) else "", cleaned
    )

    # 5. Purge verbal crutches
    cleaned = _CRUTCHES_REGEX.sub(". ", cleaned)

    # 4. Normalize punctuation artifacts
    cleaned = re.sub(r"\s+([,.:;?!])", r"\1", cleaned)
    cleaned = re.sub(r",\s*\.", ".", cleaned)
    cleaned = re.sub(r",\s*,+", ",", cleaned)
    cleaned = re.sub(r"\.\s*\.+", ".", cleaned)
    cleaned = re.sub(r"^\s*[,.:;?!]+\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # If ending lacks final punctuation, preserve or add period if looks like complete statement
    if cleaned and cleaned[-1] not in ".!?":
        cleaned += "."

    # 5. Capitalize beginnings of sentences
    return _capitalize_sentences(cleaned)


def clean_segments(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """Applies speech cleaning to a list of TranscriptSegment instances.

    Args:
        segments: List of TranscriptSegment models containing text_raw.

    Returns:
        list[TranscriptSegment]: New list with populated and sanitized text_cleaned attributes.

    Raises:
        None.
    """
    sanitized: list[TranscriptSegment] = []
    for seg in segments:
        cleaned_text = clean_speech_text(seg.text_raw)
        sanitized.append(
            TranscriptSegment(
                id=seg.id,
                start=seg.start,
                end=seg.end,
                text_raw=seg.text_raw,
                text_cleaned=cleaned_text,
            )
        )
    return sanitized
