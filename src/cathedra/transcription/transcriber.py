"""Faster-Whisper based automated lecture transcription engine.

Loads models with optimal hardware acceleration (CUDA int8_float16 or CPU int8),
applies Silero VAD filtering, and yields structured VideoTranscript models.
"""

from datetime import UTC, datetime
from pathlib import Path

from faster_whisper import WhisperModel

from cathedra.schemas import TranscriptSegment, VideoTranscript
from cathedra.transcription.bootstrap import (
    prepare_runtime_environment,
    register_windows_dll_directories,
)
from cathedra.transcription.cleaner import clean_segments, clean_speech_text

TRANSCRIPTION_LANGUAGE = "pt"
TRANSCRIPTION_VAD_FILTER = True
TRANSCRIPTION_BEAM_SIZE = 5
# Bump this revision whenever extraction, inference or cleaning behavior changes.
TRANSCRIPTION_PIPELINE_REVISION = "pcm16k-mono-cleaner-v1"


class LectureTranscriber:
    """Orchestrates Faster-Whisper audio transcription and speech cleaning.

    Attributes:
        model_size: Name or path of the Whisper model (e.g. 'large-v3', 'medium').
        device: Execution device ('cuda' or 'cpu').
        compute_type: Computation and quantization precision (e.g. 'int8_float16', 'int8').
    """

    def __init__(
        self,
        model_size: str = "large-v3",
        device: str | None = None,
        compute_type: str | None = None,
    ) -> None:
        """Initializes the transcriber, auto-resolving hardware defaults if unspecified.

        Args:
            model_size: Whisper model identifier. Defaults to 'large-v3'.
            device: Optional explicit compute device. Defaults to auto-detected runtime.
            compute_type: Optional explicit quantization. Defaults to auto-detected runtime.

        Returns:
            None.

        Raises:
            RuntimeError: If runtime dependencies cannot be satisfied.
        """
        register_windows_dll_directories()
        self.model_size = model_size

        if device is None or compute_type is None:
            runtime_info = prepare_runtime_environment()
            self.device = device if device is not None else str(runtime_info["device"])
            self.compute_type = (
                compute_type if compute_type is not None else str(runtime_info["compute_type"])
            )
        else:
            self.device = device
            self.compute_type = compute_type

        self._model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
        )

    def transcribe_file(
        self,
        audio_path: Path | str,
        discipline_slug: str,
        source_filename: str,
    ) -> VideoTranscript:
        """Transcribes a 16kHz mono audio file, producing a sanitized VideoTranscript.

        Args:
            audio_path: Path to the 16kHz mono WAV audio file.
            discipline_slug: Slug identifier of the target academic discipline.
            source_filename: Original filename of the source video.

        Returns:
            VideoTranscript: Structured and audited transcription artifact.

        Raises:
            FileNotFoundError: If the input audio file is missing on disk.
        """
        resolved_audio = Path(audio_path).resolve()
        if not resolved_audio.is_file():
            raise FileNotFoundError(f"Arquivo de áudio não encontrado: {resolved_audio}")

        segments_iter, info = self._model.transcribe(
            str(resolved_audio),
            language=TRANSCRIPTION_LANGUAGE,
            vad_filter=TRANSCRIPTION_VAD_FILTER,
            beam_size=TRANSCRIPTION_BEAM_SIZE,
        )

        raw_segments: list[TranscriptSegment] = []
        for seg in segments_iter:
            raw_text = seg.text.strip()
            raw_segments.append(
                TranscriptSegment(
                    id=seg.id,
                    start=float(seg.start),
                    end=float(seg.end),
                    text_raw=raw_text,
                    text_cleaned="",
                )
            )

        cleaned_segments = clean_segments(raw_segments)

        full_raw = " ".join(s.text_raw for s in cleaned_segments)
        full_cleaned = clean_speech_text(full_raw)

        return VideoTranscript(
            source_filename=source_filename,
            discipline_slug=discipline_slug,
            duration_seconds=float(info.duration),
            model_name=self.model_size,
            compute_type=self.compute_type,
            processed_at=datetime.now(UTC),
            full_text_raw=full_raw,
            full_text_cleaned=full_cleaned,
            segments=cleaned_segments,
        )
