"""Transcription and audio preprocessing subsystem for Cathedra.

Provides modular tools for automated environment bootstrap, audio extraction,
speech cleaning, and GPU-accelerated Whisper batch transcription.
"""

from cathedra.transcription.audio_extractor import extract_audio_to_file, extracted_audio
from cathedra.transcription.batch_runner import (
    BatchRunSummary,
    discover_lecture_videos,
    run_transcription_batch,
)
from cathedra.transcription.bootstrap import (
    check_cuda_support,
    ensure_ffmpeg,
    prepare_runtime_environment,
)
from cathedra.transcription.cleaner import clean_segments, clean_speech_text
from cathedra.transcription.transcriber import LectureTranscriber

__all__ = [
    "BatchRunSummary",
    "LectureTranscriber",
    "check_cuda_support",
    "clean_segments",
    "clean_speech_text",
    "discover_lecture_videos",
    "ensure_ffmpeg",
    "extract_audio_to_file",
    "extracted_audio",
    "prepare_runtime_environment",
    "run_transcription_batch",
]
