"""VoZii Download-Manager — mit Resume-Support fuer abgebrochene Downloads."""

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

# Expected model sizes for integrity check (approximate, in bytes)
MODEL_MIN_SIZES = {
    "tiny": 70_000_000,
    "small": 450_000_000,
    "medium": 1_400_000_000,
}


def download_file(url, dest, progress_callback=None):
    """Download mit Resume-Support (.part Datei)."""
    part_path = dest + ".part"
    existing = 0

    # Resume: wenn .part existiert, weiterladen
    if os.path.exists(part_path):
        existing = os.path.getsize(part_path)

    req = urllib.request.Request(url)
    if existing > 0:
        req.add_header("Range", f"bytes={existing}-")

    resp = urllib.request.urlopen(req)
    total = int(resp.headers.get("Content-Length", 0)) + existing

    mode = "ab" if existing > 0 else "wb"
    downloaded = existing

    with open(part_path, mode) as f:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
            if progress_callback and total > 0:
                progress_callback(downloaded, total)

    # Download fertig → .part umbenennen
    if os.path.exists(dest):
        os.remove(dest)
    os.rename(part_path, dest)
    return True


def download_and_extract_binary(gpu_type, progress_callback=None):
    os.makedirs(WHISPER_DIR, exist_ok=True)
    cli_path = os.path.join(WHISPER_DIR, "whisper-cli.exe")
    if os.path.isfile(cli_path):
        return True

    url = get_binary_url(gpu_type)
    zip_path = os.path.join(WHISPER_DIR, "whisper-cpp.zip")
    download_file(url, zip_path, progress_callback)

    extract_dir = os.path.join(WHISPER_DIR, "_extract")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    for root, _, files in os.walk(extract_dir):
        for f in files:
            src = os.path.join(root, f)
            if f.lower() in ("whisper-cli.exe", "main.exe", "whisper.exe"):
                shutil.copy2(src, os.path.join(WHISPER_DIR, "whisper-cli.exe"))
            elif f.lower().endswith(".dll"):
                shutil.copy2(src, os.path.join(WHISPER_DIR, f))

    shutil.rmtree(extract_dir, ignore_errors=True)
    os.remove(zip_path)
    return os.path.isfile(cli_path)


def download_model(model_size, progress_callback=None):
    os.makedirs(MODELS_DIR, exist_ok=True)
    filename = MODEL_FILES.get(model_size)
    if not filename:
        return False

    model_path = os.path.join(MODELS_DIR, filename)
    if is_model_installed(model_size):
        return True

    # Unvollstaendige Datei? → .part erstellen fuer Resume
    if os.path.exists(model_path):
        min_size = MODEL_MIN_SIZES.get(model_size, 0)
        if os.path.getsize(model_path) < min_size:
            os.rename(model_path, model_path + ".part")

    download_file(MODEL_URLS[model_size], model_path, progress_callback)
    return os.path.isfile(model_path)


def is_binary_installed():
    return os.path.isfile(os.path.join(WHISPER_DIR, "whisper-cli.exe"))


def is_model_installed(model_size):
    filename = MODEL_FILES.get(model_size, "")
    path = os.path.join(MODELS_DIR, filename)
    if not os.path.isfile(path):
        return False
    # Check if file is complete (not truncated)
    min_size = MODEL_MIN_SIZES.get(model_size, 0)
    return os.path.getsize(path) >= min_size
