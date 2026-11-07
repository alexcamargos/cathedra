"""Unit tests for the speech normalization and disfluency cleaning module.

Validates deterministic removal of speech fillers, hesitations, repetitive stutters,
and colloquial discourse markers while strictly preserving domain-specific terminology.
"""

from mba_wiki.schemas import TranscriptSegment
from mba_wiki.transcription.cleaner import clean_segments, clean_speech_text


def test_clean_speech_hesitations() -> None:
    """Tests removal of common vocal hesitations (é..., ah..., hum..., eh).

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    raw = "É... bom dia a todos. Ah... hoje nós vamos, hum, analisar o fluxo de caixa."
    cleaned = clean_speech_text(raw)
    assert "É..." not in cleaned
    assert "Ah..." not in cleaned
    assert "hum" not in cleaned
    assert "Bom dia a todos. Hoje nós vamos analisar o fluxo de caixa." in cleaned


def test_clean_speech_repeated_tokens() -> None:
    """Tests deduplication of repeated consecutive articles and prepositions.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    raw = "Nós vimos que que o o custo de capital depende de de premissas macroeconômicas."
    cleaned = clean_speech_text(raw)
    assert "que que" not in cleaned
    assert "o o" not in cleaned
    assert " de de " not in cleaned
    assert "Nós vimos que o custo de capital depende de premissas macroeconômicas." in cleaned


def test_clean_speech_discourse_markers() -> None:
    """Tests removal of conversational verbal crutches like 'né?', 'tipo assim'.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    raw = "O valor presente líquido deve ser positivo, né? Tipo assim, se for negativo rejeitamos."
    cleaned = clean_speech_text(raw)
    assert "né?" not in cleaned
    assert "Tipo assim" not in cleaned
    assert "O valor presente líquido deve ser positivo. Se for negativo rejeitamos." in cleaned


def test_clean_speech_preserves_technical_terms() -> None:
    """Tests that acronyms, corporate terms, and valid verbs are preserved intact.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    raw = (
        "O WACC da companhia pondera o Ke e o Kd líquido do benefício fiscal. "
        "A taxa Selic meta definida pelo Copom é de 10.5% ao ano."
    )
    cleaned = clean_speech_text(raw)
    assert "WACC" in cleaned
    assert "Ke" in cleaned
    assert "Kd" in cleaned
    assert "Selic" in cleaned
    assert "Copom" in cleaned
    assert "10.5%" in cleaned


def test_clean_speech_leading_capitalization() -> None:
    """Tests sentence capitalization adjustment after leading hesitation is pruned.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    raw = "É... então a fórmula de Black-Scholes precifica opções europeias."
    cleaned = clean_speech_text(raw)
    assert cleaned.startswith("Então a fórmula de Black-Scholes") or cleaned.startswith(
        "A fórmula de Black-Scholes"
    )


def test_clean_segments_batch() -> None:
    """Tests clean_segments batch operation populating text_cleaned on each segment.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    segments = [
        TranscriptSegment(
            id=1,
            start=0.0,
            end=4.0,
            text_raw="É... bom dia, né?",
            text_cleaned="",
        ),
        TranscriptSegment(
            id=2,
            start=4.0,
            end=9.5,
            text_raw="Hoje vamos ver o o modelo CAPM.",
            text_cleaned="",
        ),
    ]

    cleaned_list = clean_segments(segments)
    assert len(cleaned_list) == 2
    assert cleaned_list[0].text_cleaned == "Bom dia."
    assert cleaned_list[1].text_cleaned == "Hoje vamos ver o modelo CAPM."
