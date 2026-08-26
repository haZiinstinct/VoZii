"""VoZii Download-Manager — Resume, SHA256-Verifikation, Disk-Space-Preflight.

Sicherheit: Modelle und Binary-Zips werden gegen gepinnte SHA256-Hashes
geprueft (Schutz vor manipulierten Downloads), ZIP-Extraktion ist gegen
Path-Traversal abgesichert.
"""

import hashlib
import json
import logging
import os
import shutil
import time
import urllib.request
import zipfile

from src.hardware import (
    BACKEND_DLLS,
    BACKEND_VERSION,
    get_binary_sha256,
    get_binary_url,
)
from src.paths import BASE_DIR

log = logging.getLogger(__name__)

WHISPER_DIR = os.path.join(BASE_DIR, "whisper-cpp")
MODELS_DIR = os.path.join(WHISPER_DIR, "models")

# Whisper-Modelle. large-v3-turbo = modernes Diktat-Modell (8x schneller als
# large-v3, ~gleiche Qualitaet, multilingual inkl. Deutsch). tiny/small/medium
# bleiben als Keys fuer Bestandsnutzer; der Picker zeigt nur die 3 aktuellen Stufen.
# Fester Revision-Commit statt /main: aendert Upstream eine Datei, braechen sonst
# alle Downloads dauerhaft am SHA-Mismatch (LFS-Hashes am 2026-08-26 verifiziert).
_HF = ("https://huggingface.co/ggerganov/whisper.cpp/resolve/"
       "5359861c739e955e79d9a303bcbc70fb988958b1")

MODEL_URLS = {
    "tiny": f"{_HF}/ggml-tiny.bin",
    "small": f"{_HF}/ggml-small.bin",
    "medium": f"{_HF}/ggml-medium.bin",
    "large-v3-turbo-q5_0": f"{_HF}/ggml-large-v3-turbo-q5_0.bin",
    "large-v3-turbo": f"{_HF}/ggml-large-v3-turbo.bin",
}

MODEL_FILES = {
    "tiny": "ggml-tiny.bin",
    "small": "ggml-small.bin",
    "medium": "ggml-medium.bin",
    "large-v3-turbo-q5_0": "ggml-large-v3-turbo-q5_0.bin",
    "large-v3-turbo": "ggml-large-v3-turbo.bin",
}

MODEL_MIN_SIZES = {
    "tiny": 70_000_000,
    "small": 450_000_000,
    "medium": 1_400_000_000,
    "large-v3-turbo-q5_0": 520_000_000,
    "large-v3-turbo": 1_500_000_000,
}

# LFS-Hashes von huggingface.co/ggerganov/whisper.cpp (Stand 2026-06-15)
MODEL_SHA256 = {
    "tiny": "be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21",
    "small": "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b",
    "medium": "6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208",
    "large-v3-turbo-q5_0": "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2",
    "large-v3-turbo": "1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69",
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


def _extract_binaries(zip_path: str, want_cli: bool, want_server: bool, with_dlls: bool,
                      clean_first: bool = False):
    """Entpackt whitelisted Exe-Dateien (+ optional DLLs) aus dem Zip nach WHISPER_DIR.

    clean_first entfernt vorhandene exe/dll — erst NACH erfolgreichem Unzip,
    damit ein korruptes Zip den Nutzer nicht ohne Binaries zuruecklaesst."""
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

    if clean_first:
        _remove_old_binaries()

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


# Marker neben den Binaries: welches Backend in welcher Version installiert ist.
# Ohne ihn (Bestandsinstallationen) wird das Backend per DLL-Sniff erkannt.
_BACKEND_MARKER = "backend.json"


def read_backend_marker() -> dict | None:
    try:
        with open(os.path.join(WHISPER_DIR, _BACKEND_MARKER), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_backend_marker(gpu_type: str):
    try:
        with open(os.path.join(WHISPER_DIR, _BACKEND_MARKER), "w", encoding="utf-8") as f:
            json.dump({"gpu_type": gpu_type, "version": BACKEND_VERSION,
                       "installed_at": time.strftime("%Y-%m-%d")}, f)
    except OSError:
        log.warning("Backend-Marker nicht schreibbar", exc_info=True)


def installed_backend_type() -> str | None:
    """Installiertes Backend: Marker lesen, sonst DLL-Sniff (Bestandsnutzer).

    None = kein Binary installiert; "unknown" = installiert, aber nicht
    zuordenbar (wird wie veraltet behandelt)."""
    if not is_binary_installed():
        return None
    marker = read_backend_marker()
    if marker and marker.get("gpu_type") in BACKEND_DLLS:
        return marker["gpu_type"]
    try:
        files = [f.lower() for f in os.listdir(WHISPER_DIR)]
    except OSError:
        return "unknown"
    for gpu_type, patterns in BACKEND_DLLS.items():
        if any(p in f for p in patterns for f in files):
            return gpu_type
    return "unknown"


def is_backend_current(gpu_type: str) -> bool:
    """Passt das installierte Binary-Set zu gpu_type UND zur gepinnten Version?

    Bestandsinstallationen ohne Marker gelten bewusst als veraltet — sie
    stammen aus einer aelteren whisper.cpp-Version."""
    marker = read_backend_marker()
    return bool(
        is_binary_installed()
        and marker
        and marker.get("gpu_type") == gpu_type
        and marker.get("version") == BACKEND_VERSION
    )


def _remove_old_binaries():
    """Alte exe/dll vor dem Neu-Entpacken entfernen — sonst mischen sich
    CUDA-, Vulkan- und BLAS-DLLs verschiedener Versionen."""
    try:
        names = os.listdir(WHISPER_DIR)
    except OSError:
        return
    for f in names:
        if f.lower().endswith((".exe", ".dll")):
            try:
                os.remove(os.path.join(WHISPER_DIR, f))
            except OSError:
                log.warning("Konnte %s nicht entfernen", f)


def download_and_extract_binary(gpu_type, progress_callback=None):
    """Laedt das whisper.cpp-Zip und installiert CLI + Server + DLLs.

    Laedt auch bei vorhandenem Binary neu, wenn Backend-Typ oder gepinnte
    Version nicht mehr passen (frueher: Early-Return bei irgendeinem
    whisper-cli.exe — ein Backend-Wechsel installierte nie neue Binaries)."""
    os.makedirs(WHISPER_DIR, exist_ok=True)
    cli_path = os.path.join(WHISPER_DIR, "whisper-cli.exe")
    if os.path.isfile(cli_path) and is_backend_current(gpu_type):
        return True

    url = get_binary_url(gpu_type)
    zip_path = os.path.join(WHISPER_DIR, "whisper-cpp.zip")
    download_file(url, zip_path, progress_callback,
                  expected_sha256=get_binary_sha256(gpu_type))
    _extract_binaries(zip_path, want_cli=True, want_server=True, with_dlls=True,
                      clean_first=True)
    if not os.path.isfile(cli_path):
        return False
    _write_backend_marker(gpu_type)
    return True


def ensure_server_binary(gpu_type, progress_callback=None) -> bool:
    """Bestandsnutzer: CLI ist da, whisper-server.exe fehlt -> Binary-Set nachladen.

    Extrahiert CLI + Server + DLLs gemeinsam, damit alle aus derselben
    whisper.cpp-Version stammen (kein Server gegen alte DLLs).
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
        _extract_binaries(zip_path, want_cli=True, want_server=True, with_dlls=True,
                          clean_first=True)
    except InterruptedError:
        raise  # Abbruch durch den Nutzer durchreichen
    except Exception as e:
        log.warning("whisper-server.exe nachladen fehlgeschlagen (CLI-Modus bleibt): %s", e)
        return False
    if is_server_available():
        _write_backend_marker(gpu_type)
        return True
    return False


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
