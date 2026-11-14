"""Tests for the transcription telemetry and logging module.

Verifies accurate telemetry calculation, JSONL stream serialization,
and batch summary report persistence.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from mba_wiki.transcription.telemetry import (
    BatchExecutionReport,
    TranscriptionLogger,
    TranscriptionTelemetryItem,
)


def test_telemetry_item_speedup_calculation() -> None:
    """Tests that speedup factor is calculated correctly and handles zero division."""
    item = TranscriptionTelemetryItem(
        source_file="D:/video.mp4",
        relative_path="Módulo 01/Estatística/video.mp4",
        filename="video.mp4",
        discipline_slug="estatistica",
        module_slug="modulo-01",
        file_size_bytes=100_000_000,
        duration_seconds=3600.0,
        extraction_seconds=10.0,
        transcription_seconds=360.0,
        status="completed",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        segment_count=500,
        word_count=8000,
    )
    assert item.speedup_factor == pytest.approx(10.0, rel=1e-2)

    # Zero transcription seconds
    item_instant = TranscriptionTelemetryItem(
        source_file="D:/video.mp4",
        relative_path="video.mp4",
        filename="video.mp4",
        discipline_slug="geral",
        duration_seconds=100.0,
        transcription_seconds=0.0,
        status="completed",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    assert item_instant.speedup_factor == 0.0


def test_transcription_logger_writes_jsonl_and_log(tmp_path: Path) -> None:
    """Tests that TranscriptionLogger writes human log and machine JSONL lines atomically."""
    logger = TranscriptionLogger(logs_dir=tmp_path)

    item1 = TranscriptionTelemetryItem(
        source_file="D:/videos/aula1.mp4",
        relative_path="disciplina/aula1.mp4",
        filename="aula1.mp4",
        discipline_slug="disciplina",
        file_size_bytes=50_000_000,
        duration_seconds=1800.0,
        extraction_seconds=5.0,
        transcription_seconds=200.0,
        status="completed",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        segment_count=250,
        word_count=4000,
    )

    item2 = TranscriptionTelemetryItem(
        source_file="D:/videos/aula2.mp4",
        relative_path="disciplina/aula2.mp4",
        filename="aula2.mp4",
        discipline_slug="disciplina",
        status="skipped",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )

    logger.log_item(item1)
    logger.log_item(item2)

    assert logger.jsonl_path.is_file()
    assert logger.log_path.is_file()

    jsonl_content = logger.jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(jsonl_content) == 2

    log_content = logger.log_path.read_text(encoding="utf-8")
    assert "aula1.mp4" in log_content
    assert "COMPLETED" in log_content
    assert "SKIPPED" in log_content


def test_batch_execution_report_generation(tmp_path: Path) -> None:
    """Tests writing an aggregated batch report at the conclusion of a run."""
    logger = TranscriptionLogger(logs_dir=tmp_path)

    items = [
        TranscriptionTelemetryItem(
            source_file="D:/aula1.mp4",
            relative_path="aula1.mp4",
            filename="aula1.mp4",
            discipline_slug="geral",
            duration_seconds=1200.0,
            transcription_seconds=120.0,
            status="completed",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        ),
        TranscriptionTelemetryItem(
            source_file="D:/aula2.mp4",
            relative_path="aula2.mp4",
            filename="aula2.mp4",
            discipline_slug="geral",
            status="skipped",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        ),
        TranscriptionTelemetryItem(
            source_file="D:/aula3.mp4",
            relative_path="aula3.mp4",
            filename="aula3.mp4",
            discipline_slug="geral",
            status="failed",
            error_message="Corrupted video frame",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        ),
    ]

    for it in items:
        logger.log_item(it)

    report: BatchExecutionReport = logger.generate_report(
        model_name="large-v3",
        device="cuda",
        total_discovered=3,
        wall_clock_seconds=150.0,
    )

    assert report.total_discovered == 3
    assert report.total_completed == 1
    assert report.total_skipped == 1
    assert report.total_failed == 1
    assert report.total_media_duration_seconds == 1200.0
    assert report.average_speedup == pytest.approx(10.0, rel=1e-2)

    report_path = logger.save_report(report)
    assert report_path.is_file()
    assert "batch_report_" in report_path.name
