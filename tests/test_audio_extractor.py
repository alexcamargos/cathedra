"""Unit tests for the FFmpeg audio extraction module.

Validates parameter configuration for 16kHz mono PCM extraction, isolated
temporary file lifecycle management, and subprocess error handling.
"""

import subprocess
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from cathedra.transcription.audio_extractor import extract_audio_to_file, extracted_audio


def test_extracted_audio_success(tmp_path: Path, mocker: MockerFixture) -> None:
    """Tests successful audio extraction and automatic cleanup via context manager.

    Args:
        tmp_path: Pytest temporary directory fixture.
        mocker: Pytest mocker fixture.

    Returns:
        None.

    Raises:
        None.
    """
    fake_video = tmp_path / "aula_01.mp4"
    fake_video.write_bytes(b"dummy video content")

    mocker.patch(
        "cathedra.transcription.audio_extractor.ensure_ffmpeg",
        return_value=Path("C:\\tools\\ffmpeg.exe"),
    )

    def fake_subprocess_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        # Emulate FFmpeg generating the output wav
        out_wav = Path(cmd[-1])
        out_wav.write_bytes(b"RIFF dummy wav header")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    mock_run = mocker.patch("subprocess.run", side_effect=fake_subprocess_run)

    wav_path_observed: Path | None = None
    with extracted_audio(fake_video, target_dir=tmp_path) as wav_path:
        wav_path_observed = wav_path
        assert wav_path.exists()
        assert wav_path.suffix == ".wav"

        # Check FFmpeg arguments
        called_cmd = mock_run.call_args[0][0]
        assert "-vn" in called_cmd
        assert "-ar" in called_cmd
        assert "16000" in called_cmd
        assert "-ac" in called_cmd
        assert "1" in called_cmd
        assert "pcm_s16le" in called_cmd

    # After context manager exit, file must be unlinked
    assert wav_path_observed is not None
    assert not wav_path_observed.exists()


def test_extracted_audio_missing_input(tmp_path: Path) -> None:
    """Tests FileNotFoundError when input video does not exist.

    Args:
        tmp_path: Pytest temporary directory fixture.

    Returns:
        None.

    Raises:
        None.
    """
    missing_video = tmp_path / "inexistente.mp4"

    with (
        pytest.raises(FileNotFoundError, match="não foi encontrado"),
        extracted_audio(missing_video),
    ):
        pass


def test_extracted_audio_ffmpeg_error(tmp_path: Path, mocker: MockerFixture) -> None:
    """Tests RuntimeError propagation and cleanup when FFmpeg exits with non-zero code.

    Args:
        tmp_path: Pytest temporary directory fixture.
        mocker: Pytest mocker fixture.

    Returns:
        None.

    Raises:
        None.
    """
    fake_video = tmp_path / "corrupted.mp4"
    fake_video.write_bytes(b"corrupted bytes")

    mocker.patch(
        "cathedra.transcription.audio_extractor.ensure_ffmpeg",
        return_value=Path("C:\\tools\\ffmpeg.exe"),
    )
    mocker.patch(
        "subprocess.run",
        side_effect=subprocess.CalledProcessError(
            returncode=1,
            cmd=["ffmpeg"],
            stderr="Invalid data found when processing input",
        ),
    )

    with (
        pytest.raises(RuntimeError, match="Falha na extração de áudio via FFmpeg"),
        extracted_audio(fake_video, target_dir=tmp_path),
    ):
        pass


def test_extract_audio_to_file_success(tmp_path: Path, mocker: MockerFixture) -> None:
    """Tests direct extraction to a designated target file path.

    Args:
        tmp_path: Pytest temporary directory fixture.
        mocker: Pytest mocker fixture.

    Returns:
        None.

    Raises:
        None.
    """
    fake_video = tmp_path / "aula_02.mp4"
    fake_video.write_bytes(b"dummy video")
    target_wav = tmp_path / "output_custom.wav"

    mocker.patch(
        "cathedra.transcription.audio_extractor.ensure_ffmpeg",
        return_value=Path("C:\\tools\\ffmpeg.exe"),
    )

    def fake_subprocess_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        Path(cmd[-1]).write_bytes(b"RIFF dummy wav")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    mocker.patch("subprocess.run", side_effect=fake_subprocess_run)

    result_path = extract_audio_to_file(fake_video, target_wav)
    assert result_path == target_wav
    assert target_wav.exists()
