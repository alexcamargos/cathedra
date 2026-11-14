"""FFmpeg-based audio track extraction subsystem.

Converts arbitrary video formats (MP4, MKV, AVI) into normalized 16kHz mono PCM
WAV format optimized for Faster-Whisper and Silero VAD speech recognition.
"""

import subprocess
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from mba_wiki.transcription.bootstrap import ensure_ffmpeg


def extract_audio_to_file(video_path: Path | str, output_path: Path | str) -> Path:
    """Extracts the audio track from a video file to a designated WAV destination.

    Args:
        video_path: Path to the source input video file.
        output_path: Target destination path for the extracted 16kHz mono WAV file.

    Returns:
        Path: Resolved absolute path to the extracted WAV audio file.

    Raises:
        FileNotFoundError: If the source video file does not exist on disk.
        RuntimeError: If FFmpeg execution fails or exits with a non-zero code.
    """
    resolved_video = Path(video_path).resolve()
    if not resolved_video.is_file():
        raise FileNotFoundError(f"Arquivo de vídeo de origem não foi encontrado: {resolved_video}")

    resolved_output = Path(output_path).resolve()
    resolved_output.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg_bin = ensure_ffmpeg()

    cmd = [
        str(ffmpeg_bin),
        "-y",
        "-i",
        str(resolved_video),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(resolved_output),
    ]

    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr_msg = exc.stderr.strip() if exc.stderr else "Erro desconhecido"
        raise RuntimeError(
            f"Falha na extração de áudio via FFmpeg para {resolved_video.name}: {stderr_msg}"
        ) from exc

    return resolved_output


@contextmanager
def extracted_audio(
    video_path: Path | str,
    target_dir: Path | str | None = None,
) -> Iterator[Path]:
    """Context manager providing an ephemeral 16kHz mono WAV audio file with auto-cleanup.

    Args:
        video_path: Path to the source input video file.
        target_dir: Optional base directory to house the ephemeral WAV file.
            Defaults to the system temporary directory.

    Yields:
        Iterator[Path]: Yields the resolved Path to the ephemeral WAV audio file.

    Raises:
        FileNotFoundError: If the source video file does not exist on disk.
        RuntimeError: If FFmpeg audio extraction fails.
    """
    resolved_video = Path(video_path).resolve()
    if not resolved_video.is_file():
        raise FileNotFoundError(f"Arquivo de vídeo de origem não foi encontrado: {resolved_video}")

    base_dir = Path(target_dir).resolve() if target_dir is not None else Path(tempfile.gettempdir())
    base_dir.mkdir(parents=True, exist_ok=True)

    temp_filename = f"cathedra_audio_{resolved_video.stem}_{uuid.uuid4().hex[:8]}.wav"
    temp_wav_path = base_dir / temp_filename

    try:
        extract_audio_to_file(resolved_video, temp_wav_path)
        yield temp_wav_path
    finally:
        if temp_wav_path.exists():
            with suppress(OSError):
                temp_wav_path.unlink(missing_ok=True)
