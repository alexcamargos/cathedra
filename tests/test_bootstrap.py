"""Unit tests for the transcription bootstrap and auto-provisioning subsystem.

Validates automatic detection and provisioning of FFmpeg binaries and CUDA/cuDNN
hardware acceleration support for CTranslate2.
"""

from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from mba_wiki.transcription.bootstrap import (
    check_cuda_support,
    ensure_ffmpeg,
    prepare_runtime_environment,
)


def test_ensure_ffmpeg_existing(mocker: MockerFixture) -> None:
    """Tests that ensure_ffmpeg returns the path directly when ffmpeg is already in PATH.

    Args:
        mocker: Pytest mocker fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mocker.patch("shutil.which", return_value="C:\\tools\\ffmpeg.exe")
    mock_add_paths = mocker.patch("static_ffmpeg.add_paths")

    ffmpeg_path = ensure_ffmpeg()
    assert ffmpeg_path == Path("C:\\tools\\ffmpeg.exe")
    mock_add_paths.assert_not_called()


def test_ensure_ffmpeg_provisions_if_missing(mocker: MockerFixture) -> None:
    """Tests that ensure_ffmpeg triggers auto-provisioning when ffmpeg is missing initially.

    Args:
        mocker: Pytest mocker fixture.

    Returns:
        None.

    Raises:
        None.
    """
    # First call returns None (missing), second call returns provisioned path
    mocker.patch(
        "shutil.which",
        side_effect=[None, "C:\\Users\\user\\.venv\\site-packages\\static_ffmpeg\\bin\\ffmpeg.exe"],
    )
    mock_add_paths = mocker.patch("static_ffmpeg.add_paths")

    ffmpeg_path = ensure_ffmpeg()
    assert ffmpeg_path == Path(
        "C:\\Users\\user\\.venv\\site-packages\\static_ffmpeg\\bin\\ffmpeg.exe"
    )
    mock_add_paths.assert_called_once()


def test_ensure_ffmpeg_raises_when_all_fail(mocker: MockerFixture) -> None:
    """Tests that ensure_ffmpeg raises RuntimeError when provisioning fails to produce a binary.

    Args:
        mocker: Pytest mocker fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mocker.patch("shutil.which", return_value=None)
    mocker.patch("static_ffmpeg.add_paths")

    with pytest.raises(RuntimeError, match="FFmpeg"):
        ensure_ffmpeg()


def test_check_cuda_support_available(mocker: MockerFixture) -> None:
    """Tests check_cuda_support when CUDA device is detected.

    Args:
        mocker: Pytest mocker fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mocker.patch("ctranslate2.get_cuda_device_count", return_value=1)
    is_available, message = check_cuda_support()
    assert is_available is True
    assert "1" in message


def test_check_cuda_support_unavailable(mocker: MockerFixture) -> None:
    """Tests check_cuda_support when no CUDA devices are detected or exception occurs.

    Args:
        mocker: Pytest mocker fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mocker.patch("ctranslate2.get_cuda_device_count", return_value=0)
    is_available, message = check_cuda_support()
    assert is_available is False
    assert "não disponível" in message or "CPU" in message


def test_prepare_runtime_environment(mocker: MockerFixture) -> None:
    """Tests full runtime environment preparation dictionary schema.

    Args:
        mocker: Pytest mocker fixture.

    Returns:
        None.

    Raises:
        None.
    """
    mocker.patch(
        "mba_wiki.transcription.bootstrap.ensure_ffmpeg",
        return_value=Path("C:\\bin\\ffmpeg.exe"),
    )
    mocker.patch(
        "mba_wiki.transcription.bootstrap.check_cuda_support",
        return_value=(True, "CUDA operacional"),
    )

    env_info = prepare_runtime_environment()
    assert env_info["ffmpeg_path"] == "C:\\bin\\ffmpeg.exe"
    assert env_info["cuda_available"] is True
    assert env_info["device"] == "cuda"
    assert env_info["compute_type"] == "int8_float16"
