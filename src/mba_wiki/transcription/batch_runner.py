"""Batch execution orchestrator for lecture video audio transcription.

Recursively discovers recorded video lectures, tracks checkpoint progress to skip
previously transcribed sessions, and writes validated VideoTranscript artifacts atomically.
"""

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from mba_wiki.schemas import VideoTranscript
from mba_wiki.transcription.audio_extractor import extracted_audio
from mba_wiki.transcription.transcriber import LectureTranscriber

# Supported media video extensions
_SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v"}


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
    """Normalizes arbitrary folder or file names into clean URL-friendly slugs.

    Args:
        name: Raw folder or category name.

    Returns:
        str: Lowercased, hyphen-separated slug string.

    Raises:
        None.
    """
    cleaned = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE).strip().lower()
    return re.sub(r"[-\s]+", "-", cleaned) or "geral"


def discover_lecture_videos(root_dir: Path | str) -> list[tuple[Path, str]]:
    """Recursively crawls a directory discovering video files categorized by discipline.

    Args:
        root_dir: Base directory path containing lecture recordings.

    Returns:
        list[tuple[Path, str]]: List of pairs containing (video_file_path, discipline_slug).

    Raises:
        FileNotFoundError: If the base directory does not exist on disk.
    """
    resolved_root = Path(root_dir).resolve()
    if not resolved_root.is_dir():
        raise FileNotFoundError(f"Diretório de vídeos não encontrado: {resolved_root}")

    discovered: list[tuple[Path, str]] = []

    for item in sorted(resolved_root.rglob("*")):
        if item.is_file() and item.suffix.lower() in _SUPPORTED_VIDEO_EXTENSIONS:
            # Determine discipline slug based on immediate parent relative to root
            relative_parent = item.parent.relative_to(resolved_root)
            if str(relative_parent) == ".":
                discipline_slug = "geral"
            else:
                # Use top-level relative folder as discipline identifier
                discipline_slug = _slugify(relative_parent.parts[0])

            discovered.append((item, discipline_slug))

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


def run_transcription_batch(
    videos_dir: Path | str,
    output_dir: Path | str,
    transcriber: LectureTranscriber | None = None,
    force: bool = False,
) -> BatchRunSummary:
    """Executes a full batch transcription run over a directory of lecture videos.

    Args:
        videos_dir: Directory containing source video files.
        output_dir: Root output directory for structured JSON transcript artifacts.
        transcriber: Optional pre-configured LectureTranscriber instance.
            If omitted, a default instance is lazily instantiated.
        force: If True, re-transcribes videos even if valid artifacts exist.

    Returns:
        BatchRunSummary: Aggregated execution metrics and error logs.

    Raises:
        FileNotFoundError: If videos_dir does not exist.
    """
    start_time = time.perf_counter()
    discovered_videos = discover_lecture_videos(videos_dir)
    resolved_output = Path(output_dir).resolve()

    summary = BatchRunSummary(total_videos_found=len(discovered_videos))

    active_transcriber = transcriber or LectureTranscriber()

    for video_path, discipline_slug in discovered_videos:
        target_json = resolved_output / discipline_slug / f"{video_path.stem}.json"

        if not force and _is_transcript_valid(target_json):
            summary.videos_skipped += 1
            continue

        try:
            with extracted_audio(video_path) as wav_path:
                transcript = active_transcriber.transcribe_file(
                    audio_path=wav_path,
                    discipline_slug=discipline_slug,
                    source_filename=video_path.name,
                )
                _write_transcript_atomically(target_json, transcript)
                summary.videos_processed += 1
                summary.total_duration_seconds += transcript.duration_seconds
        except Exception as exc:
            summary.failed_videos.append((video_path.name, str(exc)))

    summary.elapsed_processing_seconds = time.perf_counter() - start_time
    return summary
