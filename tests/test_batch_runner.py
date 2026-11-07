"""Unit tests for the batch transcription orchestrator.

Validates recursive directory traversal, checkpoint/resume logic, atomic artifact
persistence, and failure tolerance across batch runs.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pytest_mock import MockerFixture

from mba_wiki.schemas import TranscriptSegment, VideoTranscript
from mba_wiki.transcription.batch_runner import (
    discover_lecture_videos,
    run_transcription_batch,
)


def test_discover_lecture_videos(tmp_path: Path) -> None:
    """Tests discovery of video files across nested discipline directory trees.

    Args:
        tmp_path: Pytest temporary directory fixture.

    Returns:
        None.

    Raises:
        None.
    """
    disc1 = tmp_path / "financas-corporativas"
    disc1.mkdir()
    (disc1 / "aula01.mp4").write_bytes(b"video")
    (disc1 / "aula02.mkv").write_bytes(b"video")
    (disc1 / "slides.pdf").write_bytes(b"not a video")

    disc2 = tmp_path / "estrategia"
    disc2.mkdir()
    (disc2 / "aula01.mp4").write_bytes(b"video")

    (tmp_path / "avulsa.mp4").write_bytes(b"video")

    discovered = discover_lecture_videos(tmp_path)
    assert len(discovered) == 4

    slugs = [slug for _, slug in discovered]
    assert "financas-corporativas" in slugs
    assert "estrategia" in slugs
    assert "geral" in slugs


def test_run_transcription_batch_checkpoint_and_resume(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Tests that existing valid transcripts are skipped while pending videos are transcribed.

    Args:
        tmp_path: Pytest temporary directory fixture.
        mocker: Pytest mocker fixture.

    Returns:
        None.

    Raises:
        None.
    """
    videos_dir = tmp_path / "videos"
    disc_dir = videos_dir / "marketing"
    disc_dir.mkdir(parents=True)
    video1 = disc_dir / "Aula_01.mp4"
    video2 = disc_dir / "Aula_02.mp4"
    video1.write_bytes(b"video 1")
    video2.write_bytes(b"video 2")

    output_dir = tmp_path / "output_transcripts"
    out_marketing = output_dir / "marketing"
    out_marketing.mkdir(parents=True)

    # Pre-populate valid transcript for Aula_01
    existing_transcript = VideoTranscript(
        source_filename="Aula_01.mp4",
        discipline_slug="marketing",
        duration_seconds=3600.0,
        model_name="large-v3",
        compute_type="int8_float16",
        processed_at=datetime.now(UTC),
        full_text_raw="Texto anterior.",
        full_text_cleaned="Texto anterior.",
        segments=[
            TranscriptSegment(
                id=1,
                start=0.0,
                end=10.0,
                text_raw="Texto anterior.",
                text_cleaned="Texto anterior.",
            )
        ],
    )
    (out_marketing / "Aula_01.json").write_text(
        existing_transcript.model_dump_json(indent=2), encoding="utf-8"
    )

    # Mock audio extraction context manager
    @contextmanager
    def fake_extracted_audio(v_path: Path, **kwargs: object) -> Iterator[Path]:
        temp_wav = tmp_path / f"{v_path.stem}.wav"
        temp_wav.write_bytes(b"RIFF wav")
        try:
            yield temp_wav
        finally:
            if temp_wav.exists():
                temp_wav.unlink()

    mocker.patch(
        "mba_wiki.transcription.batch_runner.extracted_audio",
        side_effect=fake_extracted_audio,
    )

    # Mock transcriber
    mock_transcriber = mocker.MagicMock()
    mock_transcriber.model_size = "large-v3"
    mock_transcriber.compute_type = "int8_float16"

    def fake_transcribe(
        audio_path: Path, discipline_slug: str, source_filename: str
    ) -> VideoTranscript:
        return VideoTranscript(
            source_filename=source_filename,
            discipline_slug=discipline_slug,
            duration_seconds=7200.0,
            model_name="large-v3",
            compute_type="int8_float16",
            processed_at=datetime.now(UTC),
            full_text_raw="Texto novo da aula 2.",
            full_text_cleaned="Texto novo da aula 2.",
            segments=[],
        )

    mock_transcriber.transcribe_file.side_effect = fake_transcribe

    summary = run_transcription_batch(
        videos_dir=videos_dir,
        output_dir=output_dir,
        transcriber=mock_transcriber,
        force=False,
    )

    assert summary.total_videos_found == 2
    assert summary.videos_skipped == 1
    assert summary.videos_processed == 1
    assert len(summary.failed_videos) == 0

    # Ensure Aula_02 was persisted
    assert (out_marketing / "Aula_02.json").is_file()
    loaded_02 = VideoTranscript.model_validate_json(
        (out_marketing / "Aula_02.json").read_text(encoding="utf-8")
    )
    assert loaded_02.source_filename == "Aula_02.mp4"
    assert loaded_02.duration_seconds == 7200.0


def test_run_transcription_batch_failure_tolerance(tmp_path: Path, mocker: MockerFixture) -> None:
    """Tests that runner continues and captures errors when a video fails processing.

    Args:
        tmp_path: Pytest temporary directory fixture.
        mocker: Pytest mocker fixture.

    Returns:
        None.

    Raises:
        None.
    """
    videos_dir = tmp_path / "videos"
    disc_dir = videos_dir / "financas"
    disc_dir.mkdir(parents=True)
    video = disc_dir / "Aula_Corrompida.mp4"
    video.write_bytes(b"corrupted")

    mocker.patch(
        "mba_wiki.transcription.batch_runner.extracted_audio",
        side_effect=RuntimeError("FFmpeg erro fatal"),
    )

    summary = run_transcription_batch(
        videos_dir=videos_dir,
        output_dir=tmp_path / "output",
        transcriber=mocker.MagicMock(),
    )

    assert summary.total_videos_found == 1
    assert summary.videos_processed == 0
    assert len(summary.failed_videos) == 1
    assert summary.failed_videos[0][0] == "Aula_Corrompida.mp4"
    assert "FFmpeg erro fatal" in summary.failed_videos[0][1]
