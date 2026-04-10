"""GPU-Erkennung und whisper.cpp Binary-URL Mapping."""

import subprocess

from src.paths import BASE_DIR

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


def detect_gpu() -> tuple[str, str]:
    """Erkennt die GPU via WMI. Returns (gpu_type, gpu_name).

    gpu_type: 'nvidia', 'amd', oder 'cpu'
    gpu_name: z.B. 'NVIDIA GeForce RTX 4070' oder 'AMD Radeon RX 6750 XT'
    """
    try:
        result = subprocess.run(
            ["wmic", "path", "win32_videocontroller", "get", "name"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        output = result.stdout
    except Exception:
        return ("cpu", "")

    lines = [line.strip() for line in output.splitlines() if line.strip() and line.strip().lower() != "name"]

    # Prioritaet: NVIDIA > AMD > CPU
    nvidia_gpu = ""
    amd_gpu = ""

    for line in lines:
        upper = line.upper()
        if "NVIDIA" in upper:
            nvidia_gpu = line
        elif "AMD" in upper or "RADEON" in upper:
            amd_gpu = line

    if nvidia_gpu:
        return ("nvidia", nvidia_gpu)
    if amd_gpu:
        return ("amd", amd_gpu)
    return ("cpu", lines[0] if lines else "")


def get_binary_url(gpu_type: str) -> str:
    return BINARY_URLS.get(gpu_type, BINARY_URLS["cpu"])


def get_backend_name(gpu_type: str) -> str:
    return BACKEND_NAMES.get(gpu_type, "CPU (BLAS)")
