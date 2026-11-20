"""Batch execution orchestrator for lecture video audio transcription.

Recursively discovers recorded video lectures, tracks checkpoint progress to skip
previously transcribed sessions, provides real-time progress callbacks, logs
detailed performance telemetry, and writes validated VideoTranscript artifacts atomically.
"""

import contextlib
import hashlib
import os
import re
import tempfile
import time
import unicodedata
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from cathedra.schemas import TranscriptCheckpoint, VideoTranscript
from cathedra.transcription.audio_extractor import extracted_audio
from cathedra.transcription.telemetry import (
    TranscriptionLogger,
    TranscriptionTelemetryItem,
)
from cathedra.transcription.transcriber import (
    TRANSCRIPTION_BEAM_SIZE,
    TRANSCRIPTION_LANGUAGE,
    TRANSCRIPTION_PIPELINE_REVISION,
    TRANSCRIPTION_VAD_FILTER,
    LectureTranscriber,
)

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
        backup_path: Preserved previous transcript when a file was replaced.
    """

    index: int
    total: int
    video: DiscoveredVideo
    phase: Literal[
        "skipped", "unverified", "start", "extracting", "transcribing", "completed", "failed"
    ]
    duration_seconds: float = 0.0
    extraction_seconds: float = 0.0
    transcription_seconds: float = 0.0
    speedup_factor: float = 0.0
    error_message: str | None = None
    backup_path: Path | None = None


@dataclass
class BatchRunSummary:
    """Execution telemetry summary for a completed transcription batch run.

    Attributes:
        total_videos_found: Total count of compatible media files discovered.
        videos_processed: Count of videos successfully transcribed and saved.
        videos_skipped: Count of videos skipped due to existing valid transcripts.
        videos_unverified: Count of existing transcripts without trustworthy checkpoint metadata.
        failed_videos: List of tuples containing (filename, error_message).
        total_duration_seconds: Cumulative media duration transcribed in seconds.
        elapsed_processing_seconds: Total wall-clock runtime in seconds.
    """

    total_videos_found: int = 0
    videos_processed: int = 0
    videos_skipped: int = 0
    videos_unverified: int = 0
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


def validate_destination_collisions(videos: list[DiscoveredVideo]) -> None:
    """Reject a batch if two videos resolve to the same transcript filename."""
    seen: dict[str, str] = {}
    for video in videos:
        relative_target = f"{video.discipline_slug}/{video.video_path.stem}.json".casefold()
        if relative_target in seen:
            raise ValueError(
                f"Colisão de destino para transcrições: {seen[relative_target]} e "
                f"{video.relative_path} -> {relative_target}"
            )
        seen[relative_target] = video.relative_path


def _video_fingerprint(path: Path) -> tuple[int, str]:
    """Hash the entire video and reject changes during the read."""
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(stream.fileno())
    current = path.stat()

    def identity(stat: os.stat_result) -> tuple[int, int, int, int]:
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)

    if identity(before) != identity(after) or identity(after) != identity(current):
        raise RuntimeError(f"Vídeo alterado durante a leitura: {path}")
    return after.st_size, digest


def _checkpoint_for_video(
    video: DiscoveredVideo, transcriber: LectureTranscriber, fingerprint: tuple[int, str]
) -> TranscriptCheckpoint:
    """Build a checkpoint from the source and effective transcription settings."""
    size, digest = fingerprint
    return TranscriptCheckpoint(
        source_relative_path=video.relative_path,
        source_size_bytes=size,
        source_sha256=digest,
        model_name=transcriber.model_size,
        device=transcriber.device,
        compute_type=transcriber.compute_type,
        language=TRANSCRIPTION_LANGUAGE,
        vad_filter=TRANSCRIPTION_VAD_FILTER,
        beam_size=TRANSCRIPTION_BEAM_SIZE,
        engine_version=version("faster-whisper"),
        pipeline_revision=TRANSCRIPTION_PIPELINE_REVISION,
    )


def _write_transcript_atomically(
    dest_json: Path, transcript: VideoTranscript, previous: bytes | None, history_dir: Path
) -> Path | None:
    """Preserve previous bytes and replace a transcript only if it has not changed."""
    if dest_json.parent.is_symlink():
        raise ValueError(f"Diretório de transcrição é um link simbólico: {dest_json.parent}")
    dest_json.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{dest_json.name}.", suffix=".tmp", dir=dest_json.parent
    )
    temporary = Path(temporary_name)
    backup: Path | None = None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(transcript.model_dump_json(indent=2))
        if dest_json.is_symlink():
            raise ValueError(f"Transcrição de destino é um link simbólico: {dest_json}")
        current = dest_json.read_bytes() if dest_json.exists() else None
        if current != previous:
            raise RuntimeError(f"Transcrição alterada durante o processamento: {dest_json}")
        if previous is not None:
            if history_dir.parent.is_symlink() or history_dir.is_symlink():
                raise ValueError(f"Diretório de histórico é um link simbólico: {history_dir}")
            history_dir.mkdir(parents=True, exist_ok=True)
            backup = history_dir / f"{dest_json.stem}.{uuid.uuid4().hex}.json"
            with backup.open("xb") as stream:
                stream.write(previous)
            if dest_json.is_symlink() or dest_json.read_bytes() != previous:
                raise RuntimeError(f"Transcrição alterada durante o processamento: {dest_json}")
        if dest_json.parent.is_symlink():
            raise ValueError(f"Diretório de transcrição é um link simbólico: {dest_json.parent}")
        os.replace(temporary, dest_json)
        return backup
    finally:
        temporary.unlink(missing_ok=True)


def migrate_legacy_transcripts(
    transcripts_root: Path | str,
    videos_dir: Path | str | None = None,
) -> int:
    """Migrates transcripts previously stored under module folders into proper discipline folders.

    Explicitly moves unambiguous legacy JSON artifacts to canonical discipline directories.
    This helper is not invoked automatically by the batch runner.

    Args:
        transcripts_root: Root directory of existing transcript JSON files.
        videos_dir: Optional source video directory to cross-reference discipline mappings.

    Returns:
        int: Number of transcript files migrated.

    Raises:
        ValueError: If discovered videos would map to the same output filename.
    """
    root = Path(transcripts_root).resolve()
    if not root.is_dir():
        return 0

    # Build video lookup map if videos_dir is provided
    video_map: dict[str, list[str]] = {}
    if videos_dir:
        v_root = Path(videos_dir).resolve()
        if v_root.is_dir():
            videos = discover_lecture_videos(v_root)
            validate_destination_collisions(videos)
            for item in videos:
                video_map.setdefault(item.video_path.name, []).append(item.discipline_slug)
                video_map.setdefault(f"{item.video_path.stem}.json", []).append(
                    item.discipline_slug
                )

    def unique_match(name: str) -> str | None:
        matches = video_map.get(name, [])
        return matches[0] if len(matches) == 1 else None

    migrated_count = 0

    for json_file in list(root.glob("*/*.json")):
        parent_name = json_file.parent.name
        # Check if parent is a module directory with diacritics or module prefix
        if "modulo" in parent_name.lower() or "módulo" in parent_name.lower():
            # Try to resolve discipline slug from video map or content
            dest_slug: str | None = unique_match(json_file.name)
            if not dest_slug:
                try:
                    data = VideoTranscript.model_validate_json(
                        json_file.read_text(encoding="utf-8")
                    )
                    dest_slug = unique_match(data.source_filename)
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
        force: Re-transcribes existing artifacts, preserving previous bytes in history.
        progress_callback: Optional callback for real-time progress events.
        logger: Optional TranscriptionLogger for structured telemetry tracking.

    Returns:
        BatchRunSummary: Aggregated execution metrics and error logs.

    Raises:
        FileNotFoundError: If videos_dir does not exist.
    """
    start_time = time.perf_counter()
    discovered_videos = discover_lecture_videos(videos_dir)
    validate_destination_collisions(discovered_videos)
    resolved_output = Path(output_dir).resolve()

    summary = BatchRunSummary(total_videos_found=len(discovered_videos))
    active_transcriber = transcriber or LectureTranscriber()
    active_logger = logger or TranscriptionLogger()

    total_count = len(discovered_videos)

    for idx, video in enumerate(discovered_videos, start=1):
        target_json = resolved_output / video.discipline_slug / f"{video.video_path.stem}.json"
        file_size = 0
        started_at = datetime.now(UTC)
        try:
            if (resolved_output / video.discipline_slug).is_symlink() or target_json.is_symlink():
                raise ValueError(f"Destino de transcrição é um link simbólico: {target_json}")
            if target_json.exists() and not target_json.is_file():
                raise ValueError(f"Destino de transcrição não é arquivo: {target_json}")
            previous = target_json.read_bytes() if target_json.exists() else None
            existing: VideoTranscript | None = None
            if previous is not None:
                with contextlib.suppress(ValueError):
                    existing = VideoTranscript.model_validate_json(previous)

            file_size, digest = _video_fingerprint(video.video_path)
            desired = _checkpoint_for_video(video, active_transcriber, (file_size, digest))
            if existing is not None and (
                existing.source_filename != video.video_path.name
                or existing.discipline_slug != video.discipline_slug
                or (
                    existing.checkpoint is not None
                    and existing.checkpoint.source_relative_path != video.relative_path
                )
            ):
                raise ValueError(f"Colisão com transcrição de outra origem: {target_json}")
            verified = (
                existing is not None
                and existing.checkpoint is not None
                and existing.model_name == existing.checkpoint.model_name
                and existing.compute_type == existing.checkpoint.compute_type
            )
            if previous is not None and not verified and not force:
                summary.videos_unverified += 1
                message = (
                    "Transcrição anterior não verificada; use --force para reprocessar com cópia."
                )
                if progress_callback:
                    progress_callback(
                        ProgressEvent(
                            index=idx,
                            total=total_count,
                            video=video,
                            phase="unverified",
                            error_message=message,
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
                        status="unverified",
                        error_message=message,
                        started_at=started_at,
                        finished_at=datetime.now(UTC),
                    )
                )
                continue
            if verified and existing is not None and existing.checkpoint == desired and not force:
                summary.videos_skipped += 1
                if progress_callback:
                    progress_callback(
                        ProgressEvent(index=idx, total=total_count, video=video, phase="skipped")
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
                    ProgressEvent(index=idx, total=total_count, video=video, phase="start")
                )

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
                if _video_fingerprint(video.video_path) != (file_size, digest):
                    raise RuntimeError(f"Vídeo alterado durante a transcrição: {video.video_path}")
                if (
                    transcript.source_filename != video.video_path.name
                    or transcript.discipline_slug != video.discipline_slug
                    or transcript.model_name != desired.model_name
                    or transcript.compute_type != desired.compute_type
                ):
                    raise ValueError(
                        "A transcrição retornada não corresponde à origem ou configuração."
                    )
                transcript.checkpoint = desired
                if (
                    verified
                    and existing is not None
                    and existing.checkpoint is not None
                    and existing.checkpoint.source_sha256 == digest
                ):
                    transcript.lesson_number = existing.lesson_number
                backup_path = _write_transcript_atomically(
                    target_json,
                    transcript,
                    previous,
                    resolved_output / ".history" / video.discipline_slug,
                )
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
                            backup_path=backup_path,
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
                        backup_path=str(backup_path) if backup_path else None,
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
