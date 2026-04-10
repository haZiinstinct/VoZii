"""Download-Manager mit Progress-Callbacks fuer GUI-Integration."""

import os
import shutil
import urllib.request
import zipfile

from src.paths import BASE_DIR
from src.hardware import get_binary_url

WHISPER_DIR = os.path.join(BASE_DIR, "whisper-cpp")
MODELS_DIR = os.path.join(WHISPER_DIR, "models")

MODEL_URLS = {
    "tiny": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin",
    "small": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin",
    "medium": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin",
}

MODEL_FILES = {
    "tiny": "ggml-tiny.bin",
    "small": "ggml-small.bin",
    "medium": "ggml-medium.bin",
}


def download_file(url: str, dest: str, progress_callback=None) -> bool:
    """Download a file. progress_callback(downloaded_bytes, total_bytes) wird periodisch aufgerufen."""
    def reporthook(block_num, block_size, total_size):
        if progress_callback and total_size > 0:
            downloaded = block_num * block_size
            progress_callback(min(downloaded, total_size), total_size)

    try:
        urllib.request.urlretrieve(url, dest, reporthook)
        return True
    except Exception as e:
        if os.path.exists(dest):
            os.remove(dest)
        raise


def download_and_extract_binary(gpu_type: str, progress_callback=None) -> bool:
    """Laedt whisper.cpp Binary fuer den erkannten GPU-Typ herunter und entpackt sie."""
    os.makedirs(WHISPER_DIR, exist_ok=True)

    cli_path = os.path.join(WHISPER_DIR, "whisper-cli.exe")
    if os.path.isfile(cli_path):
        return True  # Already installed

    url = get_binary_url(gpu_type)
    zip_path = os.path.join(WHISPER_DIR, "whisper-cpp.zip")

    download_file(url, zip_path, progress_callback)

    # Extract
    extract_dir = os.path.join(WHISPER_DIR, "_extract")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    # Find and copy executables + DLLs
    exe_found = False
    for root, dirs, files in os.walk(extract_dir):
        for f in files:
            src = os.path.join(root, f)
            if f.lower() in ("whisper-cli.exe", "main.exe", "whisper.exe"):
                shutil.copy2(src, os.path.join(WHISPER_DIR, "whisper-cli.exe"))
                exe_found = True
            elif f.lower().endswith(".dll"):
                shutil.copy2(src, os.path.join(WHISPER_DIR, f))

    if not exe_found:
        for root, dirs, files in os.walk(extract_dir):
            for f in files:
                if f.endswith(".exe"):
                    shutil.copy2(os.path.join(root, f), os.path.join(WHISPER_DIR, f))

    shutil.rmtree(extract_dir, ignore_errors=True)
    if os.path.exists(zip_path):
        os.remove(zip_path)

    return os.path.isfile(cli_path)


def download_model(model_size: str, progress_callback=None) -> bool:
    """Laedt ein Whisper GGML Modell herunter."""
    os.makedirs(MODELS_DIR, exist_ok=True)

    filename = MODEL_FILES.get(model_size)
    if not filename:
        return False

    model_path = os.path.join(MODELS_DIR, filename)
    if os.path.isfile(model_path):
        return True  # Already downloaded

    url = MODEL_URLS[model_size]
    download_file(url, model_path, progress_callback)
    return os.path.isfile(model_path)


def is_binary_installed() -> bool:
    return os.path.isfile(os.path.join(WHISPER_DIR, "whisper-cli.exe"))


def is_model_installed(model_size: str) -> bool:
    filename = MODEL_FILES.get(model_size, "")
    return os.path.isfile(os.path.join(MODELS_DIR, filename))
