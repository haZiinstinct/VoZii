"""GPU-Erkennung und whisper.cpp Binary-URL Mapping."""

import logging
import subprocess
import threading

log = logging.getLogger(__name__)

# whisper.cpp pre-built binaries fuer verschiedene GPUs
BINARY_URLS = {
    "nvidia": "https://github.com/ggml-org/whisper.cpp/releases/download/v1.8.4/whisper-cublas-12.4.0-bin-x64.zip",
    "amd": "https://github.com/jerryshell/whisper.cpp-windows-vulkan-bin/releases/download/v1.0.0/whisper.cpp-windows-vulkan.zip",
    "cpu": "https://github.com/ggml-org/whisper.cpp/releases/download/v1.8.4/whisper-blas-bin-x64.zip",
}

# SHA256 der Release-Zips (GitHub-Asset-Digests, gepinnt am 2026-06-11).
# Aendert sich ein Upstream-Asset, schlaegt der Download bewusst fehl.
BINARY_SHA256 = {
    "nvidia": "b07cff4e59831b227896018facbb6334907bf324a342c84597c44f087823d252",
    "amd": "a5d408c72e460433b39875f74a0b6e27e60a3724301d478fe9873db7ff4098e0",
    "cpu": "d85e60bdba2dcb35cf42fd07c0cd1481ef6ca631f81872c1f2204ea8cdb7d001",
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


def detect_gpu_cached(config: dict) -> tuple[str, str, bool]:
    """GPU-Erkennung mit Config-Cache — wmic/PowerShell kosten bis zu 10s
    und blockierten bisher jeden App-Start.

    Cache vorhanden: sofort zurueckgeben + im Hintergrund neu erkennen
    (Aenderung wirkt ab dem naechsten Start). Erststart: synchron + cachen.
    Returns (gpu_type, gpu_name, from_cache).
    """
    cached_type = config.get("gpu_cache_type")
    if cached_type in BINARY_URLS:
        cached_name = config.get("gpu_cache_name") or ""
        threading.Thread(target=_refresh_gpu_cache,
                         args=(cached_type, cached_name), daemon=True).start()
        return cached_type, cached_name, True

    gpu_type, gpu_name = detect_gpu()
    _store_gpu_cache(gpu_type, gpu_name)
    return gpu_type, gpu_name, False


def _refresh_gpu_cache(old_type: str, old_name: str):
    try:
        gpu_type, gpu_name = detect_gpu()
        if (gpu_type, gpu_name) != (old_type, old_name):
            _store_gpu_cache(gpu_type, gpu_name)
            log.info("GPU-Cache aktualisiert: %s (%s) — wirkt ab dem naechsten Start",
                     gpu_name or "CPU", gpu_type)
    except Exception:
        log.exception("GPU-Cache-Refresh fehlgeschlagen")


def _store_gpu_cache(gpu_type: str, gpu_name: str):
    # Lazy-Import vermeidet einen Import-Zyklus (config braucht paths, wir
    # werden von downloader importiert)
    from src.config import load_config, save_config
    try:
        cfg = load_config()
        cfg["gpu_cache_type"] = gpu_type
        cfg["gpu_cache_name"] = gpu_name
        save_config(cfg)
    except Exception:
        log.exception("GPU-Cache speichern fehlgeschlagen")


def get_binary_url(gpu_type: str) -> str:
    return BINARY_URLS.get(gpu_type, BINARY_URLS["cpu"])


def get_binary_sha256(gpu_type: str) -> str:
    return BINARY_SHA256.get(gpu_type, BINARY_SHA256["cpu"])


def get_backend_name(gpu_type: str) -> str:
    return BACKEND_NAMES.get(gpu_type, "CPU (BLAS)")
