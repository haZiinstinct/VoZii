"""VoZii Download-Manager — Resume, SHA256-Verifikation, Disk-Space-Preflight.

Sicherheit: Modelle und Binary-Zips werden gegen gepinnte SHA256-Hashes
geprueft (Schutz vor manipulierten Downloads), ZIP-Extraktion ist gegen
Path-Traversal abgesichert.
"""

import hashlib
import logging
import os
import shutil
import time
import urllib.request
import zipfile

from src.hardware import get_binary_sha256, get_binary_url
from src.paths import BASE_DIR

log = logging.getLogger(__name__)

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

MODEL_MIN_SIZES = {
    "tiny": 70_000_000,
    "small": 450_000_000,
    "medium": 1_400_000_000,
}

# LFS-Hashes von huggingface.co/ggerganov/whisper.cpp (Stand 2026-06-11)
MODEL_SHA256 = {
    "tiny": "be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21",
    "small": "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b",
    "medium": "6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208",
}

# 500 MB Puffer, damit Windows/andere Apps nicht auf 0 laufen
_DISK_SPACE_BUFFER = 500 * 1024 * 1024

# CLI-Namen je nach whisper.cpp-Version (aeltere Releases: main.exe)
_CLI_NAMES = ("whisper-cli.exe", "main.exe", "whisper.exe")


def _sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _ensure_disk_space(dest_dir: str, required_bytes: int):
    """Raised RuntimeError wenn nicht genug Platz fuer Download + Puffer da ist."""
    try:
        free = shutil.disk_usage(dest_dir or ".").free
    except OSError:
        return  # Pruefung scheitert -> Download trotzdem versuchen
    if free < required_bytes + _DISK_SPACE_BUFFER:
        need_mb = (required_bytes + _DISK_SPACE_BUFFER) // 1048576
        free_mb = free // 1048576
        raise RuntimeError(
            f"Zu wenig Speicherplatz: {need_mb} MB benoetigt, {free_mb} MB frei.\n"
            f"Bitte Platz schaffen und erneut versuchen."
        )


def download_file(url, dest, progress_callback=None, expected_sha256=None):
    """Download mit Resume-Support (.part Datei). Raised RuntimeError bei Fehler.

    progress_callback(downloaded, total, speed_bps)
    expected_sha256: wenn gesetzt, wird die fertige Datei verifiziert und
    bei Mismatch geloescht.
    """
    part_path = dest + ".part"
    existing = 0

    if os.path.exists(part_path):
        existing = os.path.getsize(part_path)

    req = urllib.request.Request(url)
    if existing > 0:
        req.add_header("Range", f"bytes={existing}-")

    try:
        resp = urllib.request.urlopen(req)
    except Exception as e:
        raise RuntimeError(f"Verbindung fehlgeschlagen: {e}") from e

    # Resume nur wenn der Server den Range-Request akzeptiert (206 Partial
    # Content). Bei 200 liefert er die ganze Datei -> .part verwerfen,
    # sonst entsteht eine korrupte Doppel-Datei.
    status = getattr(resp, "status", 200)
    if existing > 0 and status != 206:
        log.warning("Server ignoriert Range-Request (HTTP %s) — Download startet neu", status)
        existing = 0

    total = int(resp.headers.get("Content-Length", 0) or 0) + existing
    if total > existing:
        _ensure_disk_space(os.path.dirname(dest), total - existing)

    mode = "ab" if existing > 0 else "wb"
    downloaded = existing
    last_update = time.time()
    last_bytes = downloaded

    try:
        with open(part_path, mode) as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if progress_callback and total > 0 and now - last_update >= 0.2:
                    speed = (downloaded - last_bytes) / (now - last_update)
                    progress_callback(downloaded, total, speed)
                    last_update = now
                    last_bytes = downloaded
    except OSError as e:
        # Disk voll, Permission-Fehler etc.
        raise RuntimeError(f"Schreiben fehlgeschlagen (evtl. Festplatte voll): {e}") from e

    if progress_callback and total > 0:
        progress_callback(downloaded, total, 0)

    # Download fertig → .part umbenennen
    if os.path.exists(dest):
        os.remove(dest)
    os.rename(part_path, dest)

    if expected_sha256:
        actual = _sha256_of(dest)
        if actual.lower() != expected_sha256.lower():
            os.remove(dest)
            log.error("SHA256-Mismatch fuer %s: erwartet %s, erhalten %s",
                      url, expected_sha256, actual)
            raise RuntimeError(
                "Checksumme des Downloads stimmt nicht — Datei wurde verworfen.\n"
                "Bitte erneut versuchen. Bleibt der Fehler, bitte als Issue melden."
            )

    return True


def _safe_extract(zf: zipfile.ZipFile, extract_dir: str):
    """extractall mit Path-Traversal-Schutz (../evil.exe im Zip)."""
    base = os.path.realpath(extract_dir)
    for member in zf.namelist():
        target = os.path.realpath(os.path.join(extract_dir, member))
        if target != base and not target.startswith(base + os.sep):
            raise RuntimeError(f"Unsicherer Pfad im Zip-Archiv: {member}")
    zf.extractall(extract_dir)


def _extract_binaries(zip_path: str, want_cli: bool, want_server: bool, with_dlls: bool):
    """Entpackt whitelisted Exe-Dateien (+ optional DLLs) aus dem Zip nach WHISPER_DIR."""
    extract_dir = os.path.join(WHISPER_DIR, "_extract")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            _safe_extract(zf, extract_dir)
    except (zipfile.BadZipFile, OSError) as e:
        log.error("ZIP extract fehlgeschlagen: %s", e)
        if os.path.exists(zip_path):
            os.remove(zip_path)
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise RuntimeError(f"Download ist beschaedigt. Bitte erneut versuchen: {e}") from e

    for root, _, files in os.walk(extract_dir):
        for f in files:
            src = os.path.join(root, f)
            lower = f.lower()
            if want_cli and lower in _CLI_NAMES:
                shutil.copy2(src, os.path.join(WHISPER_DIR, "whisper-cli.exe"))
            elif want_server and lower == "whisper-server.exe":
                shutil.copy2(src, os.path.join(WHISPER_DIR, "whisper-server.exe"))
            elif with_dlls and lower.endswith(".dll"):
                shutil.copy2(src, os.path.join(WHISPER_DIR, f))

    shutil.rmtree(extract_dir, ignore_errors=True)
    os.remove(zip_path)


def download_and_extract_binary(gpu_type, progress_callback=None):
    """Laedt das whisper.cpp-Zip und installiert CLI + Server + DLLs."""
    os.makedirs(WHISPER_DIR, exist_ok=True)
    cli_path = os.path.join(WHISPER_DIR, "whisper-cli.exe")
    if os.path.isfile(cli_path):
        return True

    url = get_binary_url(gpu_type)
    zip_path = os.path.join(WHISPER_DIR, "whisper-cpp.zip")
    download_file(url, zip_path, progress_callback,
                  expected_sha256=get_binary_sha256(gpu_type))
    _extract_binaries(zip_path, want_cli=True, want_server=True, with_dlls=True)
    return os.path.isfile(cli_path)


def ensure_server_binary(gpu_type, progress_callback=None) -> bool:
    """Bestandsnutzer: CLI ist da, whisper-server.exe fehlt -> nur Server nachladen.

    Best-effort — bei Fehlern bleibt der CLI-Modus voll funktionsfaehig.
    """
    if is_server_available():
        return True
    if not is_binary_installed():
        return False
    try:
        url = get_binary_url(gpu_type)
        zip_path = os.path.join(WHISPER_DIR, "whisper-cpp.zip")
        download_file(url, zip_path, progress_callback,
                      expected_sha256=get_binary_sha256(gpu_type))
        _extract_binaries(zip_path, want_cli=False, want_server=True, with_dlls=False)
    except InterruptedError:
        raise  # Abbruch durch den Nutzer durchreichen
    except Exception as e:
        log.warning("whisper-server.exe nachladen fehlgeschlagen (CLI-Modus bleibt): %s", e)
        return False
    return is_server_available()


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

    download_file(MODEL_URLS[model_size], model_path, progress_callback,
                  expected_sha256=MODEL_SHA256.get(model_size))
    return os.path.isfile(model_path)


def is_binary_installed():
    return os.path.isfile(os.path.join(WHISPER_DIR, "whisper-cli.exe"))


def is_server_available():
    return os.path.isfile(os.path.join(WHISPER_DIR, "whisper-server.exe"))


def is_model_installed(model_size):
    filename = MODEL_FILES.get(model_size, "")
    path = os.path.join(MODELS_DIR, filename)
    if not os.path.isfile(path):
        return False
    min_size = MODEL_MIN_SIZES.get(model_size, 0)
    return os.path.getsize(path) >= min_size
