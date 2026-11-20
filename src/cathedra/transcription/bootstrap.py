"""Automated bootstrap and runtime provisioning for transcription dependencies.

Detects and ensures availability of FFmpeg binaries and CUDA/cuDNN hardware
acceleration for CTranslate2 and Faster-Whisper.
"""

import contextlib
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import ctranslate2


def register_windows_dll_directories() -> None:
    """Discovers and registers NVIDIA and virtualenv DLL search paths on Windows.

    Injects DLL directories both into os.add_dll_directory and process PATH to ensure
    native CTranslate2 C++ loaders discover CUDA and cuDNN runtime libraries.

    Returns:
        None.

    Raises:
        None.
    """
    if sys.platform != "win32":
        return

    # Check site-packages directories for any nvidia runtime DLL folders
    for base_path in sys.path:
        site_path = Path(base_path)
        if not site_path.is_dir():
            continue

        nvidia_dir = site_path / "nvidia"
        if nvidia_dir.is_dir():
            for sub in nvidia_dir.iterdir():
                bin_dir = sub / "bin"
                if bin_dir.is_dir():
                    resolved_bin = str(bin_dir.resolve())
                    if hasattr(os, "add_dll_directory"):
                        with contextlib.suppress(OSError, ValueError):
                            os.add_dll_directory(resolved_bin)
                    current_path = os.environ.get("PATH", "")
                    if resolved_bin not in current_path:
                        os.environ["PATH"] = f"{resolved_bin};{current_path}"


def ensure_ffmpeg() -> Path:
    """Verifies that an FFmpeg executable is available, downloading it automatically if missing.

    Returns:
        Path: Absolute path to the verified FFmpeg executable.

    Raises:
        RuntimeError: If FFmpeg is neither found in system PATH nor able to be provisioned.
    """
    # 1. Check existing PATH
    existing = shutil.which("ffmpeg")
    if existing is not None:
        return Path(existing).resolve()

    # 2. Check local application cache directory
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        cached_binary = Path(local_app_data) / "cathedra" / "bin" / "ffmpeg.exe"
        if cached_binary.is_file():
            os.environ["PATH"] = f"{cached_binary.parent.resolve()};{os.environ.get('PATH', '')}"
            return cached_binary.resolve()

    # 3. Trigger auto-provisioning via static-ffmpeg
    try:
        import static_ffmpeg

        static_ffmpeg.add_paths()
    except Exception:
        pass

    # 4. Check if static-ffmpeg added it to PATH
    after_provision = shutil.which("ffmpeg")
    if after_provision is not None:
        return Path(after_provision).resolve()

    raise RuntimeError(
        "FFmpeg não foi localizado no sistema e o provisionamento automático falhou. "
        "Certifique-se de que o executável 'ffmpeg' esteja instalado ou acessível."
    )


def check_cuda_support() -> tuple[bool, str]:
    """Inspects CTranslate2 CUDA device availability and hardware support.

    Returns:
        tuple[bool, str]: Boolean indicating CUDA availability and human-readable diagnostics.

    Raises:
        None.
    """
    register_windows_dll_directories()

    try:
        device_count = ctranslate2.get_cuda_device_count()
        if device_count > 0:
            msg = f"Aceleração CUDA operacional com {device_count} dispositivo(s) detectado(s)."
            return True, msg
        return False, "Nenhum dispositivo CUDA detectado; fallback para CPU."
    except Exception as exc:
        return False, f"Falha na detecção de suporte CUDA ({exc}); fallback para CPU."


def prepare_runtime_environment() -> dict[str, Any]:
    """Prepares and validates the full execution environment for transcription jobs.

    Returns:
        dict[str, Any]: Dictionary containing verified ffmpeg path, device, and compute type.

    Raises:
        RuntimeError: If mandatory dependencies like FFmpeg cannot be provisioned.
    """
    ffmpeg_path = ensure_ffmpeg()
    cuda_available, cuda_msg = check_cuda_support()

    device = "cuda" if cuda_available else "cpu"
    compute_type = "int8_float16" if cuda_available else "int8"

    return {
        "ffmpeg_path": str(ffmpeg_path),
        "cuda_available": cuda_available,
        "cuda_status": cuda_msg,
        "device": device,
        "compute_type": compute_type,
    }
