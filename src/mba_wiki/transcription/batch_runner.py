"""Batch execution orchestrator for lecture video audio transcription.

Recursively discovers recorded video lectures, tracks checkpoint progress to skip
previously transcribed sessions, provides real-time progress callbacks, logs
detailed performance telemetry, and writes validated VideoTranscript artifacts atomically.
"""

import os
import re
import time
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from mba_wiki.schemas import VideoTranscript
from mba_wiki.transcription.audio_extractor import extracted_audio
from mba_wiki.transcription.telemetry import (
    TranscriptionLogger,
    TranscriptionTelemetryItem,
)
from mba_wiki.transcription.transcriber import LectureTranscriber

# Supported media video extensions
_SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v"}


@dataclass
class DiscoveredVideo:
    """Represents a discovered video file with its associated discipline and module context.

    Attributes:
        video_path: Absolute filesystem path to the video file.
        discipline_slug: Clean ASCII slug of the associated discipline.
        module_slug: Clean ASCII slug of the parent module, if applicable.
        relative_path: Path relative to the crawled root directory.
    """

    video_path: Path
    discipline_slug: str
    module_slug: str | None = None
    relative_path: str = ""

    def __iter__(self) -> Iterator[Path | str]:
        """Allows unpacking as (video_path, discipline_slug) for backward compatibility."""
        return iter((self.video_path, self.discipline_slug))


@dataclass
class ProgressEvent:
    """Event data emitted to progress listeners during batch processing.

    Attributes:
        index: 1-based index of current video.
        total: Total number of videos in batch.
        video: Discovered video information.
        phase: Current execution phase.
        duration_seconds: Media duration in seconds (if available).
        extraction_seconds: Time spent on FFmpeg audio extraction.
        transcription_seconds: Time spent on Faster-Whisper transcription.
        speedup_factor: Computed speedup against real-time playback.
        error_message: Error description if phase is 'failed'.
    """

    index: int
    total: int
    video: DiscoveredVideo
    phase: Literal["skipped", "start", "extracting", "transcribing", "completed", "failed"]
    duration_seconds: float = 0.0
    extraction_seconds: float = 0.0
    transcription_seconds: float = 0.0
    speedup_factor: float = 0.0
    error_message: str | None = None


@dataclass
class BatchRunSummary:
    """Execution telemetry summary for a completed transcription batch run.

    Attributes:
        total_videos_found: Total count of compatible media files discovered.
        videos_processed: Count of videos successfully transcribed and saved.
        videos_skipped: Count of videos skipped due to existing valid transcripts.
        failed_videos: List of tuples containing (filename, error_message).
        total_duration_seconds: Cumulative media duration transcribed in seconds.
        elapsed_processing_seconds: Total wall-clock runtime in seconds.
    """

    total_videos_found: int = 0
    videos_processed: int = 0
    videos_skipped: int = 0
    failed_videos: list[tuple[str, str]] = field(default_factory=list)
    total_duration_seconds: float = 0.0
    elapsed_processing_seconds: float = 0.0


def _slugify(name: str) -> str:
    """Normalizes arbitrary folder or file names into clean ASCII URL-friendly slugs.

    Removes diacritics and converts non-alphanumeric characters into hyphens.

    Args:
        name: Raw folder or category name.

    Returns:
        str: Lowercased, hyphen-separated ASCII slug string.

    Raises:
        None.
    """
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("utf-8")
    cleaned = re.sub(r"[^\w\s-]", "", normalized).strip().lower()
    return re.sub(r"[-\s]+", "-", cleaned) or "geral"


def discover_lecture_videos(root_dir: Path | str) -> list[DiscoveredVideo]:
    """Recursively crawls a directory discovering video files categorized by discipline.

    Resolves academic module hierarchy when present (e.g. 'Módulo 01.../Disciplina/Aula.mp4')
    assigning the true discipline slug to the inner folder and preserving the parent module.

    Args:
        root_dir: Base directory path containing lecture recordings.

    Returns:
        list[DiscoveredVideo]: List of discovered videos with discipline and module slugs.

    Raises:
        FileNotFoundError: If the base directory does not exist on disk.
    """
    resolved_root = Path(root_dir).resolve()
    if not resolved_root.is_dir():
        raise FileNotFoundError(f"Diretório de vídeos não encontrado: {resolved_root}")

    discovered: list[DiscoveredVideo] = []

    for item in sorted(resolved_root.rglob("*")):
        if item.is_file() and item.suffix.lower() in _SUPPORTED_VIDEO_EXTENSIONS:
            relative_parent = item.parent.relative_to(resolved_root)
            parts = relative_parent.parts

            if not parts:
                discipline_slug = "geral"
                module_slug = None
            elif len(parts) == 1:
                # Top-level standalone category (e.g. 'Extras e TCC', 'Palestras')
                discipline_slug = _slugify(parts[0])
                module_slug = None
            else:
                # Hierarchical layout: First part is module, second part is discipline
                module_slug = _slugify(parts[0])
                discipline_slug = _slugify(parts[1])

            rel_str = str(item.relative_to(resolved_root)).replace("\\", "/")
            discovered.append(
                DiscoveredVideo(
                    video_path=item,
                    discipline_slug=discipline_slug,
                    module_slug=module_slug,
                    relative_path=rel_str,
                )
            )

    return discovered


def _is_transcript_valid(dest_json: Path) -> bool:
    """Verifies whether an existing transcript artifact exists and is structurally intact.

    Args:
        dest_json: Path to the candidate transcript JSON file.

    Returns:
        bool: True if the file exists and passes Pydantic schema validation.

    Raises:
        None.
    """
    if not dest_json.is_file():
        return False

    try:
        content = dest_json.read_text(encoding="utf-8")
        VideoTranscript.model_validate_json(content)
        return True
    except Exception:
        return False


def _write_transcript_atomically(dest_json: Path, transcript: VideoTranscript) -> None:
    """Writes a VideoTranscript model to disk using an atomic rename operation.

    Args:
        dest_json: Final intended target path for the JSON artifact.
        transcript: Validated VideoTranscript model to serialize.

    Returns:
        None.

    Raises:
        OSError: If writing or renaming fails.
    """
    dest_json.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_json.with_suffix(".tmp")

    json_payload = transcript.model_dump_json(indent=2)
    temp_path.write_text(json_payload, encoding="utf-8")
    os.replace(temp_path, dest_json)


def migrate_legacy_transcripts(
    transcripts_root: Path | str,
    videos_dir: Path | str | None = None,
) -> int:
    """Migrates transcripts previously stored under module folders into proper discipline folders.

    Inspects legacy directories containing diacritics or module names and moves JSON artifacts
    to their canonical discipline slug directory without requiring re-transcription.

    Args:
        transcripts_root: Root directory of existing transcript JSON files.
        videos_dir: Optional source video directory to cross-reference discipline mappings.

    Returns:
        int: Number of transcript files migrated.

    Raises:
        None.
    """
    root = Path(transcripts_root).resolve()
    if not root.is_dir():
        return 0

    # Build video lookup map if videos_dir is provided
    video_map: dict[str, str] = {}
    if videos_dir:
        v_root = Path(videos_dir).resolve()
        if v_root.is_dir():
            for item in discover_lecture_videos(v_root):
                video_map[item.video_path.name] = item.discipline_slug
                video_map[f"{item.video_path.stem}.json"] = item.discipline_slug

    migrated_count = 0

    for json_file in list(root.glob("*/*.json")):
        parent_name = json_file.parent.name
        # Check if parent is a module directory with diacritics or module prefix
        if "modulo" in parent_name.lower() or "módulo" in parent_name.lower():
            # Try to resolve discipline slug from video map or content
            dest_slug: str | None = video_map.get(json_file.name)
            if not dest_slug:
                try:
                    data = VideoTranscript.model_validate_json(
                        json_file.read_text(encoding="utf-8")
                    )
                    dest_slug = video_map.get(data.source_filename)
                except Exception:
                    dest_slug = None

            if dest_slug and dest_slug != parent_name:
                target_dir = root / dest_slug
                target_dir.mkdir(parents=True, exist_ok=True)
                target_file = target_dir / json_file.name
                if not target_file.exists():
                    os.replace(json_file, target_file)
                    migrated_count += 1

    return migrated_count


def run_transcription_batch(
    videos_dir: Path | str,
    output_dir: Path | str,
    transcriber: LectureTranscriber | None = None,
    force: bool = False,
    progress_callback: Callable[[ProgressEvent], None] | None = None,
    logger: TranscriptionLogger | None = None,
) -> BatchRunSummary:
    """Executes a full batch transcription run over a directory of lecture videos.

    Args:
        videos_dir: Directory containing source video files.
        output_dir: Root output directory for structured JSON transcript artifacts.
        transcriber: Optional pre-configured LectureTranscriber instance.
            If omitted, a default instance is lazily instantiated.
        force: If True, re-transcribes videos even if valid artifacts exist.
        progress_callback: Optional callback for real-time progress events.
        logger: Optional TranscriptionLogger for structured telemetry tracking.

    Returns:
        BatchRunSummary: Aggregated execution metrics and error logs.

    Raises:
        FileNotFoundError: If videos_dir does not exist.
    """
    start_time = time.perf_counter()
    discovered_videos = discover_lecture_videos(videos_dir)
    resolved_output = Path(output_dir).resolve()

    # Attempt migration of legacy transcript files if any exist
    migrate_legacy_transcripts(resolved_output, videos_dir=videos_dir)

    summary = BatchRunSummary(total_videos_found=len(discovered_videos))
    active_transcriber = transcriber or LectureTranscriber()
    active_logger = logger or TranscriptionLogger()

    total_count = len(discovered_videos)

    for idx, video in enumerate(discovered_videos, start=1):
        target_json = resolved_output / video.discipline_slug / f"{video.video_path.stem}.json"
        file_size = video.video_path.stat().st_size if video.video_path.is_file() else 0
        started_at = datetime.now(UTC)

        if not force and _is_transcript_valid(target_json):
            summary.videos_skipped += 1
            if progress_callback:
                progress_callback(
                    ProgressEvent(
                        index=idx,
                        total=total_count,
                        video=video,
                        phase="skipped",
                    )
                )
            active_logger.log_item(
                TranscriptionTelemetryItem(
                    source_file=str(video.video_path),
                    relative_path=video.relative_path,
                    filename=video.video_path.name,
                    discipline_slug=video.discipline_slug,
                    module_slug=video.module_slug,
                    file_size_bytes=file_size,
                    status="skipped",
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                )
            )
            continue

        if progress_callback:
            progress_callback(
                ProgressEvent(
                    index=idx,
                    total=total_count,
                    video=video,
                    phase="start",
                )
            )

        try:
            # 1. Audio extraction phase
            extract_start = time.perf_counter()
            if progress_callback:
                progress_callback(
                    ProgressEvent(
                        index=idx,
                        total=total_count,
                        video=video,
                        phase="extracting",
                    )
                )

            with extracted_audio(video.video_path) as wav_path:
                extract_seconds = time.perf_counter() - extract_start

                # 2. Faster-Whisper transcription phase
                transcribe_start = time.perf_counter()
                if progress_callback:
                    progress_callback(
                        ProgressEvent(
                            index=idx,
                            total=total_count,
                            video=video,
                            phase="transcribing",
                            extraction_seconds=extract_seconds,
                        )
                    )

                transcript = active_transcriber.transcribe_file(
                    audio_path=wav_path,
                    discipline_slug=video.discipline_slug,
                    source_filename=video.video_path.name,
                )
                transcribe_seconds = time.perf_counter() - transcribe_start

                # 3. Persistence
                _write_transcript_atomically(target_json, transcript)
                summary.videos_processed += 1
                summary.total_duration_seconds += transcript.duration_seconds

                speedup = (
                    transcript.duration_seconds / transcribe_seconds
                    if transcribe_seconds > 0.0
                    else 0.0
                )
                finished_at = datetime.now(UTC)

                word_count = len(transcript.full_text_cleaned.split())

                if progress_callback:
                    progress_callback(
                        ProgressEvent(
                            index=idx,
                            total=total_count,
                            video=video,
                            phase="completed",
                            duration_seconds=transcript.duration_seconds,
                            extraction_seconds=extract_seconds,
                            transcription_seconds=transcribe_seconds,
                            speedup_factor=speedup,
                        )
                    )

                active_logger.log_item(
                    TranscriptionTelemetryItem(
                        source_file=str(video.video_path),
                        relative_path=video.relative_path,
                        filename=video.video_path.name,
                        discipline_slug=video.discipline_slug,
                        module_slug=video.module_slug,
                        file_size_bytes=file_size,
                        duration_seconds=transcript.duration_seconds,
                        extraction_seconds=extract_seconds,
                        transcription_seconds=transcribe_seconds,
                        segment_count=len(transcript.segments),
                        word_count=word_count,
                        status="completed",
                        started_at=started_at,
                        finished_at=finished_at,
                    )
                )

        except Exception as exc:
            summary.failed_videos.append((video.video_path.name, str(exc)))
            if progress_callback:
                progress_callback(
                    ProgressEvent(
                        index=idx,
                        total=total_count,
                        video=video,
                        phase="failed",
                        error_message=str(exc),
                    )
                )
            active_logger.log_item(
                TranscriptionTelemetryItem(
                    source_file=str(video.video_path),
                    relative_path=video.relative_path,
                    filename=video.video_path.name,
                    discipline_slug=video.discipline_slug,
                    module_slug=video.module_slug,
                    file_size_bytes=file_size,
                    status="failed",
                    error_message=str(exc),
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                )
            )

    summary.elapsed_processing_seconds = time.perf_counter() - start_time

    # Generate and persist batch summary report
    report = active_logger.generate_report(
        model_name=getattr(active_transcriber, "model_size", "unknown"),
        device=getattr(active_transcriber, "device", "unknown"),
        total_discovered=summary.total_videos_found,
        wall_clock_seconds=summary.elapsed_processing_seconds,
    )
    active_logger.save_report(report)

    return summary
