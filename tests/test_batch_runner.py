"""Unit tests for the batch transcription orchestrator.

Validates recursive directory traversal, checkpoint/resume logic, atomic artifact
persistence, hierarchical discipline extraction, and progress telemetry across batch runs.
"""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from pytest_mock import MockerFixture

from cathedra.schemas import TranscriptCheckpoint, TranscriptSegment, VideoTranscript
from cathedra.transcription.batch_runner import (
    ProgressEvent,
    discover_lecture_videos,
    migrate_legacy_transcripts,
    run_transcription_batch,
)
from cathedra.transcription.telemetry import TranscriptionLogger
from cathedra.transcription.transcriber import (
    TRANSCRIPTION_BEAM_SIZE,
    TRANSCRIPTION_LANGUAGE,
    TRANSCRIPTION_PIPELINE_REVISION,
    TRANSCRIPTION_VAD_FILTER,
)


def test_discover_lecture_videos_hierarchical(tmp_path: Path) -> None:
    """Tests discovery of video files across nested module and discipline directory trees.

    Args:
        tmp_path: Pytest temporary directory fixture.

    Returns:
        None.

    Raises:
        None.
    """
    # 2-level hierarchical structure
    mod1 = tmp_path / "Módulo 01 - Fundamentos" / "Fundamentos de Estatística"
    mod1.mkdir(parents=True)
    (mod1 / "aula01.mp4").write_bytes(b"video 1")
    (mod1 / "aula02.mkv").write_bytes(b"video 2")

    # 1-level standalone structure
    extras = tmp_path / "Extras e TCC"
    extras.mkdir(parents=True)
    (extras / "tcc.mp4").write_bytes(b"video 3")

    # Root video
    (tmp_path / "avulso.mp4").write_bytes(b"video 4")

    discovered = discover_lecture_videos(tmp_path)
    assert len(discovered) == 4

    # Test tuple unpacking for backward compatibility
    unpacked = [(p.name, slug) for p, slug in discovered]
    assert ("aula01.mp4", "fundamentos-de-estatistica") in unpacked
    assert ("tcc.mp4", "extras-e-tcc") in unpacked
    assert ("avulso.mp4", "geral") in unpacked

    # Test module_slug preservation
    aula1_item = next(it for it in discovered if it.video_path.name == "aula01.mp4")
    assert aula1_item.module_slug == "modulo-01-fundamentos"
    assert aula1_item.discipline_slug == "fundamentos-de-estatistica"


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
        checkpoint=TranscriptCheckpoint(
            source_relative_path="marketing/Aula_01.mp4",
            source_size_bytes=video1.stat().st_size,
            source_sha256=hashlib.sha256(video1.read_bytes()).hexdigest(),
            model_name="large-v3",
            device="cuda",
            compute_type="int8_float16",
            language=TRANSCRIPTION_LANGUAGE,
            vad_filter=TRANSCRIPTION_VAD_FILTER,
            beam_size=TRANSCRIPTION_BEAM_SIZE,
            engine_version=version("faster-whisper"),
            pipeline_revision=TRANSCRIPTION_PIPELINE_REVISION,
        ),
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
        "cathedra.transcription.batch_runner.extracted_audio",
        side_effect=fake_extracted_audio,
    )

    # Mock transcriber
    mock_transcriber = mocker.MagicMock()
    mock_transcriber.model_size = "large-v3"
    mock_transcriber.compute_type = "int8_float16"
    mock_transcriber.device = "cuda"

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

    events: list[ProgressEvent] = []

    def on_progress(ev: ProgressEvent) -> None:
        events.append(ev)

    logger = TranscriptionLogger(logs_dir=tmp_path / "logs")

    summary = run_transcription_batch(
        videos_dir=videos_dir,
        output_dir=output_dir,
        transcriber=mock_transcriber,
        force=False,
        progress_callback=on_progress,
        logger=logger,
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

    # Verify progress events
    phases = [e.phase for e in events]
    assert "skipped" in phases
    assert "start" in phases
    assert "extracting" in phases
    assert "transcribing" in phases
    assert "completed" in phases

    # Verify telemetry logs written
    assert logger.jsonl_path.is_file()
    assert logger.log_path.is_file()


def test_migrate_legacy_transcripts(tmp_path: Path) -> None:
    """Tests migration of legacy transcript files from module dirs into discipline dirs."""
    transcripts_dir = tmp_path / "transcripts"
    legacy_mod = transcripts_dir / "módulo-01-fundamentos"
    legacy_mod.mkdir(parents=True)

    videos_dir = tmp_path / "videos"
    disc_dir = videos_dir / "Módulo 01 - Fundamentos" / "Fundamentos de Estatística"
    disc_dir.mkdir(parents=True)
    video_file = disc_dir / "aula_estatistica.mp4"
    video_file.write_bytes(b"vid")

    t_data = VideoTranscript(
        source_filename="aula_estatistica.mp4",
        discipline_slug="módulo-01-fundamentos",
        duration_seconds=3600.0,
        model_name="large-v3",
        compute_type="int8_float16",
        processed_at=datetime.now(UTC),
        full_text_raw="Texto",
        full_text_cleaned="Texto",
        segments=[],
    )
    (legacy_mod / "aula_estatistica.json").write_text(
        t_data.model_dump_json(indent=2), encoding="utf-8"
    )

    migrated = migrate_legacy_transcripts(transcripts_dir, videos_dir=videos_dir)
    assert migrated == 1

    target_file = transcripts_dir / "fundamentos-de-estatistica" / "aula_estatistica.json"
    assert target_file.is_file()


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
        "cathedra.transcription.batch_runner.extracted_audio",
        side_effect=RuntimeError("FFmpeg erro fatal"),
    )

    mock_transcriber = mocker.MagicMock()
    mock_transcriber.model_size = "large-v3"
    mock_transcriber.device = "cpu"
    mock_transcriber.compute_type = "int8"
    summary = run_transcription_batch(
        videos_dir=videos_dir,
        output_dir=tmp_path / "output",
        transcriber=mock_transcriber,
    )

    assert summary.total_videos_found == 1
    assert summary.videos_processed == 0
    assert len(summary.failed_videos) == 1
    assert summary.failed_videos[0][0] == "Aula_Corrompida.mp4"
    assert "FFmpeg erro fatal" in summary.failed_videos[0][1]
