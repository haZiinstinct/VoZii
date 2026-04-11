"""GPU-Erkennung und whisper.cpp Binary-URL Mapping."""

import logging
import subprocess

log = logging.getLogger(__name__)

# whisper.cpp pre-built binaries fuer verschiedene GPUs
BINARY_URLS = {
    "nvidia": "https://github.com/ggml-org/whisper.cpp/releases/download/v1.8.4/whisper-cublas-12.4.0-bin-x64.zip",
    "amd": "https://github.com/jerryshell/whisper.cpp-windows-vulkan-bin/releases/download/v1.0.0/whisper.cpp-windows-vulkan.zip",
    "cpu": "https://github.com/ggml-org/whisper.cpp/releases/download/v1.8.4/whisper-blas-bin-x64.zip",
}

BACKEND_NAMES = {
    "nvidia": "CUDA 12.4",
    "amd": "Vulkan",
    "cpu": "CPU (BLAS)",
}

# DLLs die auf den korrekten Backend hinweisen
BACKEND_DLLS = {
    "nvidia": ["cublas64"],
    "amd": ["ggml-vulkan.dll"],
    "cpu": ["openblas"],
}


def _try_wmic() -> str | None:
    """Versuch 1: wmic (schnell, aber in neueren Win11 deprecated)."""
    try:
        result = subprocess.run(
            ["wmic", "path", "win32_videocontroller", "get", "name"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=5, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except Exception:
        pass
    return None


def _try_powershell() -> str | None:
    """Versuch 2: PowerShell Get-CimInstance (funktioniert ohne wmic)."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except Exception:
        pass
    return None


def detect_gpu() -> tuple[str, str]:
    """Erkennt die GPU via WMI/PowerShell. Returns (gpu_type, gpu_name).

    gpu_type: 'nvidia', 'amd', oder 'cpu'
    gpu_name: z.B. 'NVIDIA GeForce RTX 4070' oder 'AMD Radeon RX 6750 XT'
    """
    output = _try_wmic()
    if not output:
        log.info("wmic nicht verfuegbar, versuche PowerShell...")
        output = _try_powershell()
    if not output:
        log.warning("GPU-Erkennung fehlgeschlagen, fallback auf CPU")
        return ("cpu", "")

    lines = [line.strip() for line in output.splitlines()
             if line.strip() and line.strip().lower() != "name"]

    # Prioritaet: nvidia > amd > intel (als cpu) > cpu
    for line in lines:
        if "NVIDIA" in line.upper():
            return ("nvidia", line)
    for line in lines:
        upper = line.upper()
        if "AMD" in upper or "RADEON" in upper:
            return ("amd", line)
    for line in lines:
        upper = line.upper()
        if "INTEL" in upper:
            # Intel GPUs (iGPU oder ARC) → CPU-Binary (kein dediziertes Intel-Binary verfuegbar)
            return ("cpu", line)

    return ("cpu", lines[0] if lines else "")


def get_binary_url(gpu_type: str) -> str:
    return BINARY_URLS.get(gpu_type, BINARY_URLS["cpu"])


def get_backend_name(gpu_type: str) -> str:
    return BACKEND_NAMES.get(gpu_type, "CPU (BLAS)")
