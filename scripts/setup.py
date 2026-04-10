"""
Setup-Script: Laedt whisper.cpp und das Whisper-Modell herunter.

Nutzung:
    python scripts/setup.py              # Vulkan GPU + small Modell (Standard)
    python scripts/setup.py --cpu        # CPU-only Build
    python scripts/setup.py --model tiny # Anderes Modell waehlen
"""

import argparse
import os
import sys
import urllib.request
import zipfile
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WHISPER_DIR = os.path.join(BASE_DIR, "whisper-cpp")
MODELS_DIR = os.path.join(WHISPER_DIR, "models")

# whisper.cpp pre-built binaries
VULKAN_URL = "https://github.com/jerryshell/whisper.cpp-windows-vulkan-bin/releases/download/v1.0.0/whisper.cpp-windows-vulkan.zip"
CPU_URL = "https://github.com/ggml-org/whisper.cpp/releases/download/v1.8.4/whisper-blas-bin-x64.zip"

# Whisper GGML models on Hugging Face
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


def download_file(url: str, dest: str, label: str = ""):
    """Download a file with progress indicator."""
    if os.path.exists(dest):
        print(f"  [SKIP] {label or dest} existiert bereits")
        return

    print(f"  [DOWNLOAD] {label or url}")

    class ProgressReporter:
        def __init__(self):
            self.last_pct = -1

        def __call__(self, block_num, block_size, total_size):
            if total_size > 0:
                pct = int(block_num * block_size * 100 / total_size)
                pct = min(pct, 100)
                if pct != self.last_pct and pct % 10 == 0:
                    print(f"    {pct}%", end=" ", flush=True)
                    self.last_pct = pct

    try:
        urllib.request.urlretrieve(url, dest, ProgressReporter())
        print()  # newline after progress
    except Exception as e:
        print(f"\n  [FEHLER] Download fehlgeschlagen: {e}")
        if os.path.exists(dest):
            os.remove(dest)
        raise


def setup_whisper_binary(use_vulkan: bool = True):
    """Download and extract whisper.cpp binary."""
    os.makedirs(WHISPER_DIR, exist_ok=True)

    # Check if already set up
    cli_path = os.path.join(WHISPER_DIR, "whisper-cli.exe")
    if os.path.isfile(cli_path):
        print(f"[OK] whisper-cli.exe bereits vorhanden")
        return

    url = VULKAN_URL if use_vulkan else CPU_URL
    mode = "Vulkan GPU" if use_vulkan else "CPU (BLAS)"
    print(f"\n=== whisper.cpp herunterladen ({mode}) ===")

    zip_path = os.path.join(WHISPER_DIR, "whisper-cpp.zip")
    download_file(url, zip_path, f"whisper.cpp ({mode})")

    print("  [EXTRACT] Entpacke...")
    extract_dir = os.path.join(WHISPER_DIR, "_extract")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    # Find whisper-cli.exe or main.exe in extracted files
    exe_found = False
    for root, dirs, files in os.walk(extract_dir):
        for f in files:
            src = os.path.join(root, f)
            if f.lower() in ("whisper-cli.exe", "main.exe", "whisper.exe"):
                dst = os.path.join(WHISPER_DIR, "whisper-cli.exe")
                shutil.copy2(src, dst)
                exe_found = True
                print(f"  [OK] {f} -> whisper-cli.exe")
            elif f.lower().endswith(".dll"):
                dst = os.path.join(WHISPER_DIR, f)
                shutil.copy2(src, dst)

    if not exe_found:
        # List what we found for debugging
        print("  [WARN] Kein whisper-cli.exe gefunden. Gefundene Dateien:")
        for root, dirs, files in os.walk(extract_dir):
            for f in files:
                if f.endswith(".exe"):
                    print(f"    - {os.path.relpath(os.path.join(root, f), extract_dir)}")
        # Copy all .exe files
        for root, dirs, files in os.walk(extract_dir):
            for f in files:
                if f.endswith(".exe"):
                    src = os.path.join(root, f)
                    dst = os.path.join(WHISPER_DIR, f)
                    shutil.copy2(src, dst)
                    print(f"  [COPY] {f}")

    # Cleanup
    shutil.rmtree(extract_dir, ignore_errors=True)
    os.remove(zip_path)


def setup_model(model_size: str = "small"):
    """Download Whisper GGML model."""
    os.makedirs(MODELS_DIR, exist_ok=True)

    filename = MODEL_FILES.get(model_size)
    if not filename:
        print(f"[FEHLER] Unbekanntes Modell: {model_size}. Verfuegbar: {', '.join(MODEL_FILES.keys())}")
        sys.exit(1)

    model_path = os.path.join(MODELS_DIR, filename)
    url = MODEL_URLS[model_size]

    print(f"\n=== Whisper Modell herunterladen ({model_size}) ===")
    download_file(url, model_path, f"{filename}")
    print(f"  [OK] Modell gespeichert: {model_path}")


def verify_setup():
    """Verify all components are in place."""
    print("\n=== Pruefe Installation ===")
    cli_path = os.path.join(WHISPER_DIR, "whisper-cli.exe")
    ok = True

    if os.path.isfile(cli_path):
        size_mb = os.path.getsize(cli_path) / (1024 * 1024)
        print(f"  [OK] whisper-cli.exe ({size_mb:.1f} MB)")
    else:
        print(f"  [FEHLER] whisper-cli.exe nicht gefunden")
        ok = False

    for name, filename in MODEL_FILES.items():
        path = os.path.join(MODELS_DIR, filename)
        if os.path.isfile(path):
            size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f"  [OK] {filename} ({size_mb:.0f} MB)")

    if ok:
        print("\n[FERTIG] Setup abgeschlossen! Starte mit: python src/main.py")
    else:
        print("\n[FEHLER] Setup unvollstaendig. Siehe Fehler oben.")

    return ok


def main():
    parser = argparse.ArgumentParser(description="Voice-to-Text Tool Setup")
    parser.add_argument("--cpu", action="store_true", help="CPU-only Build statt Vulkan GPU")
    parser.add_argument("--model", default="small", choices=["tiny", "small", "medium"],
                        help="Whisper Modellgroesse (default: small)")
    args = parser.parse_args()

    print("=" * 50)
    print("  Voice-to-Text Tool — Setup")
    print("=" * 50)

    setup_whisper_binary(use_vulkan=not args.cpu)
    setup_model(args.model)
    verify_setup()


if __name__ == "__main__":
    main()
