"""GPU-Erkennung und whisper.cpp Binary-URL Mapping."""

import logging
import subprocess
import threading

log = logging.getLogger(__name__)

# whisper.cpp pre-built binaries fuer verschiedene GPUs — alle aus dem eigenen
# Mirror-Release backend-v<version> (stabile URLs, kein Dritt-Repo/kein
# beweglicher Upstream-Ref mehr): nvidia/cpu = gespiegelte offizielle Zips
# (Digest-verifiziert), amd = eigener Vulkan-Build aus dem Upstream-Source
# (.github/workflows/build-backend.yml).
BACKEND_VERSION = "1.9.2"
_MIRROR = f"https://github.com/haZiinstinct/VoZii/releases/download/backend-v{BACKEND_VERSION}"

BINARY_URLS = {
    "nvidia": f"{_MIRROR}/whisper-cublas-12.4.0-bin-x64.zip",
    "amd": f"{_MIRROR}/whisper-vulkan-bin-x64.zip",
    "cpu": f"{_MIRROR}/whisper-blas-bin-x64.zip",
}

# SHA256 der Release-Zips (GitHub-Asset-Digests, gepinnt am 2026-08-26).
# Aendert sich ein Asset, schlaegt der Download bewusst fehl.
BINARY_SHA256 = {
    "nvidia": "443110ddaad70d4290ab2e77179e31cf712035bbc4fad56bb4519a90c917b39c",
    "amd": "b6d8d381b16dcdc73d547b60d071c43b58980b458dd7e65327abd2c989e86f15",
    "cpu": "ffe5b47ca8e53a7677949f23a9c4641bbec4eee8a5714c3d14b67bb8d7b24a78",
}

BACKEND_NAMES = {
    "nvidia": "CUDA 12.4",
    "amd": "Vulkan",
    "cpu": "CPU (BLAS)",
}

# DLL-Namensmuster, die das installierte Backend verraten (Migration von
# Bestandsinstallationen ohne backend.json-Marker; Reihenfolge = Prioritaet)
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
        log.debug("GPU-Cache-Refresh fehlgeschlagen", exc_info=True)


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
