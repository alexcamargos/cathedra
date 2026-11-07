"""Unit tests for the Faster-Whisper lecture transcription engine.

Validates model instantiation, GPU/CPU runtime resolution, audio file transcription,
VAD integration, and serialization into VideoTranscript models.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pytest_mock import MockerFixture

from mba_wiki.transcription.transcriber import LectureTranscriber


@dataclass
class DummySegment:
    """Mock object mimicking faster_whisper.transcribe.Segment."""

    id: int
    start: float
    end: float
    text: str


@dataclass
class DummyTranscriptionInfo:
    """Mock object mimicking faster_whisper.transcribe.TranscriptionInfo."""

    duration: float
    language: str = "pt"


def test_transcriber_initialization_defaults(mocker: MockerFixture) -> None:
    """Tests LectureTranscriber initialization using environment auto-detection.

    Args:
        mocker: Pytest mocker fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mocker.patch(
        "mba_wiki.transcription.transcriber.prepare_runtime_environment",
        return_value={
            "device": "cuda",
            "compute_type": "int8_float16",
        },
    )
    mock_model_cls = mocker.patch("mba_wiki.transcription.transcriber.WhisperModel")

    transcriber = LectureTranscriber()
    assert transcriber.model_size == "large-v3"
    assert transcriber.device == "cuda"
    assert transcriber.compute_type == "int8_float16"

    mock_model_cls.assert_called_once_with(
        "large-v3",
        device="cuda",
        compute_type="int8_float16",
    )


def test_transcriber_initialization_custom(mocker: MockerFixture) -> None:
    """Tests LectureTranscriber initialization with explicit user parameters.

    Args:
        mocker: Pytest mocker fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mock_model_cls = mocker.patch("mba_wiki.transcription.transcriber.WhisperModel")

    transcriber = LectureTranscriber(
        model_size="medium",
        device="cpu",
        compute_type="int8",
    )
    assert transcriber.model_size == "medium"
    assert transcriber.device == "cpu"
    assert transcriber.compute_type == "int8"

    mock_model_cls.assert_called_once_with(
        "medium",
        device="cpu",
        compute_type="int8",
    )


def test_transcribe_file_success(tmp_path: Path, mocker: MockerFixture) -> None:
    """Tests full transcription run producing a structured VideoTranscript.

    Args:
        tmp_path: Pytest temporary directory fixture.
        mocker: Pytest mocker fixture.

    Returns:
        None.

    Raises:
        None.
    """
    dummy_wav = tmp_path / "aula.wav"
    dummy_wav.write_bytes(b"RIFF dummy wav")

    raw_segments = [
        DummySegment(
            id=1,
            start=0.0,
            end=5.0,
            text="É... bom dia, hoje falaremos de governança corporativa, né?",
        ),
        DummySegment(
            id=2,
            start=5.0,
            end=12.0,
            text="O conselho de de administração monitora a diretoria executiva.",
        ),
    ]

    def fake_transcribe(
        audio_path: str, **kwargs: Any
    ) -> tuple[Iterator[DummySegment], DummyTranscriptionInfo]:
        info = DummyTranscriptionInfo(duration=120.5)
        return iter(raw_segments), info

    mock_instance = mocker.MagicMock()
    mock_instance.transcribe.side_effect = fake_transcribe
    mocker.patch("mba_wiki.transcription.transcriber.WhisperModel", return_value=mock_instance)

    transcriber = LectureTranscriber(device="cpu", compute_type="int8")
    result = transcriber.transcribe_file(
        audio_path=dummy_wav,
        discipline_slug="governanca-corporativa",
        source_filename="Aula_01_Governanca.mp4",
    )

    assert result.source_filename == "Aula_01_Governanca.mp4"
    assert result.discipline_slug == "governanca-corporativa"
    assert result.duration_seconds == 120.5
    assert len(result.segments) == 2

    # Verify cleaning applied to segment text
    assert result.segments[0].text_cleaned == "Bom dia, hoje falaremos de governança corporativa."
    assert " de de " not in result.segments[1].text_cleaned
    assert "O conselho de administração" in result.segments[1].text_cleaned

    # Verify full texts
    assert "É... bom dia" in result.full_text_raw
    assert "É..." not in result.full_text_cleaned
