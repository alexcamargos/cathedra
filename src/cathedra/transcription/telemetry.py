"""Telemetry tracking and detailed structured logging for lecture transcription.

Provides machine-readable JSONL logs, human-readable execution audits,
and post-run performance profiling metrics for audio extraction and inference.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class TranscriptionTelemetryItem(BaseModel):
    """Detailed telemetry record for a single lecture video transcription attempt.

    Attributes:
        source_file: Absolute path of the processed video.
        relative_path: Path relative to the crawled root directory.
        filename: Base name of the file.
        discipline_slug: Clean ASCII slug of the associated discipline.
        module_slug: Clean ASCII slug of the parent module, if applicable.
        file_size_bytes: Size of the video file in bytes.
        duration_seconds: Total media duration transcribed in seconds.
        extraction_seconds: Wall-clock time spent on FFmpeg audio conversion.
        transcription_seconds: Wall-clock time spent on Faster-Whisper GPU/CPU inference.
        segment_count: Total number of discrete speech segments transcribed.
        word_count: Total word count in cleaned transcript.
        status: Final outcome (completed, skipped, unverified, or failed).
        error_message: Optional error description if the operation failed.
        backup_path: Path of a preserved previous transcript, if any.
        started_at: UTC timestamp when processing of this file began.
        finished_at: UTC timestamp when processing completed.
        speedup_factor: Computed acceleration ratio (duration / transcription_time).
    """

    source_file: str
    relative_path: str
    filename: str
    discipline_slug: str
    module_slug: str | None = None
    file_size_bytes: int = 0
    duration_seconds: float = 0.0
    extraction_seconds: float = 0.0
    transcription_seconds: float = 0.0
    segment_count: int = 0
    word_count: int = 0
    status: Literal["completed", "skipped", "unverified", "failed"]
    error_message: str | None = None
    backup_path: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def speedup_factor(self) -> float:
        """Calculates the execution speedup ratio against real-time playback.

        Returns:
            float: Multiple of real-time speed (e.g. 10.5 for 10.5x real-time),
                or 0.0 if transcription time is zero.
        """
        if self.transcription_seconds <= 0.0:
            return 0.0
        return self.duration_seconds / self.transcription_seconds


class BatchExecutionReport(BaseModel):
    """Aggregated execution summary report for a complete transcription batch run.

    Attributes:
        run_id: Unique identifier string for the batch execution run.
        model_name: Faster-Whisper model used.
        device: Compute hardware device used (cuda or cpu).
        total_discovered: Total video media files discovered in the search directory.
        total_completed: Number of files successfully processed and written to disk.
        total_skipped: Number of files bypassed due to pre-existing valid transcripts.
        total_unverified: Existing transcripts without verifiable checkpoint metadata.
        total_failed: Number of files that encountered unhandled exceptions.
        total_media_duration_seconds: Cumulative audio duration of all processed videos.
        total_wall_clock_seconds: Total wall-clock runtime for the entire batch.
        average_speedup: Average speedup factor across completed files.
        started_at: Batch run start timestamp.
        finished_at: Batch run completion timestamp.
        items: List of individual telemetry items captured during the run.
    """

    run_id: str
    model_name: str
    device: str
    total_discovered: int
    total_completed: int
    total_skipped: int
    total_unverified: int = 0
    total_failed: int
    total_media_duration_seconds: float
    total_wall_clock_seconds: float
    average_speedup: float
    started_at: datetime
    finished_at: datetime
    items: list[TranscriptionTelemetryItem] = Field(default_factory=list)


class TranscriptionLogger:
    """Manages append-only JSONL telemetry and human-readable log files for transcription.

    Attributes:
        logs_dir: Root directory where log files and telemetry lines are persisted.
        jsonl_path: Path to the active daily JSONL telemetry stream file.
        log_path: Path to the active daily text log file.
    """

    def __init__(self, logs_dir: Path | str | None = None) -> None:
        """Initializes the transcription logger, ensuring parent directories exist.

        Args:
            logs_dir: Optional custom log directory. Defaults to 'logs/transcriptions'.

        Returns:
            None.

        Raises:
            None.
        """
        self.logs_dir = Path(logs_dir) if logs_dir else Path("logs/transcriptions")
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        self.jsonl_path = self.logs_dir / f"telemetry_{date_str}.jsonl"
        self.log_path = self.logs_dir / f"transcription_{date_str}.log"
        self._items: list[TranscriptionTelemetryItem] = []

    def log_item(self, item: TranscriptionTelemetryItem) -> None:
        """Appends a completed telemetry record to memory, disk JSONL, and text log.

        Args:
            item: Completed TranscriptionTelemetryItem record.

        Returns:
            None.

        Raises:
            OSError: If writing to disk fails.
        """
        self._items.append(item)

        # Write to JSONL
        json_line = item.model_dump_json() + "\n"
        with self.jsonl_path.open("a", encoding="utf-8") as f_jsonl:
            f_jsonl.write(json_line)

        # Write formatted text line
        now_str = item.finished_at.strftime("%Y-%m-%d %H:%M:%S")
        if item.status == "completed":
            dur_min = item.duration_seconds / 60
            speed = f"{item.speedup_factor:.1f}x"
            msg = (
                f"[{now_str}] COMPLETED | {item.discipline_slug} | {item.filename} | "
                f"Audio: {dur_min:.1f}min | Extr: {item.extraction_seconds:.1f}s | "
                f"Whisper: {item.transcription_seconds:.1f}s ({speed}) | "
                f"Words: {item.word_count}"
            )
            if item.backup_path:
                msg += f" | Backup: {item.backup_path}"
        elif item.status == "skipped":
            msg = (
                f"[{now_str}] SKIPPED   | {item.discipline_slug} | {item.filename} | "
                "Valid transcript already exists"
            )
        elif item.status == "unverified":
            msg = (
                f"[{now_str}] UNVERIFIED | {item.discipline_slug} | {item.filename} | "
                f"{item.error_message}"
            )
        else:
            msg = (
                f"[{now_str}] FAILED    | {item.discipline_slug} | {item.filename} | "
                f"Error: {item.error_message}"
            )

        with self.log_path.open("a", encoding="utf-8") as f_log:
            f_log.write(msg + "\n")

    def generate_report(
        self,
        model_name: str,
        device: str,
        total_discovered: int,
        wall_clock_seconds: float,
    ) -> BatchExecutionReport:
        """Calculates aggregated metrics and compiles a comprehensive BatchExecutionReport.

        Args:
            model_name: Faster-Whisper model used.
            device: Computing device used (cuda/cpu).
            total_discovered: Total count of discovered video files.
            wall_clock_seconds: Total elapsed seconds for the entire batch.

        Returns:
            BatchExecutionReport: Compiled metrics report.

        Raises:
            None.
        """
        completed = [it for it in self._items if it.status == "completed"]
        skipped = [it for it in self._items if it.status == "skipped"]
        unverified = [it for it in self._items if it.status == "unverified"]
        failed = [it for it in self._items if it.status == "failed"]

        total_audio_sec = sum(it.duration_seconds for it in completed)
        total_whisper_sec = sum(it.transcription_seconds for it in completed)

        avg_speedup = total_audio_sec / total_whisper_sec if total_whisper_sec > 0.0 else 0.0

        run_id = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

        return BatchExecutionReport(
            run_id=run_id,
            model_name=str(model_name),
            device=str(device),
            total_discovered=total_discovered,
            total_completed=len(completed),
            total_skipped=len(skipped),
            total_unverified=len(unverified),
            total_failed=len(failed),
            total_media_duration_seconds=total_audio_sec,
            total_wall_clock_seconds=wall_clock_seconds,
            average_speedup=avg_speedup,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            items=list(self._items),
        )

    def save_report(self, report: BatchExecutionReport) -> Path:
        """Saves a BatchExecutionReport to a formatted JSON file in the logs directory.

        Args:
            report: The BatchExecutionReport model instance to persist.

        Returns:
            Path: The path to the saved report JSON file.

        Raises:
            OSError: If saving fails.
        """
        out_path = self.logs_dir / f"batch_report_{report.run_id}.json"
        payload = report.model_dump_json(indent=2)
        out_path.write_text(payload, encoding="utf-8")
        return out_path
