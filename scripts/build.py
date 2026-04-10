"""
VoZii Build-Script: Erstellt standalone .exe mit PyInstaller.

Nutzung:
    python scripts/build.py
"""

import os
import shutil
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(BASE_DIR, "dist", "VoZii")


def build():
    print("=" * 50)
    print("  VoZii — Build")
    print("=" * 50)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--console",               # Console fuer Debug — --windowed fuer Release
        "--name", "VoZii",
        "--add-data", f"{os.path.join(BASE_DIR, 'config.default.yaml')};.",
        "--hidden-import", "pynput.keyboard._win32",
        "--hidden-import", "pynput.mouse._win32",
        "--hidden-import", "PIL._tkinter_finder",
        "--collect-submodules", "pynput",
        "--collect-all", "customtkinter",
        os.path.join(BASE_DIR, "src", "main.py"),
    ]

    print("\n[BUILD] Starte PyInstaller...")
    result = subprocess.run(cmd, cwd=BASE_DIR)

    if result.returncode != 0:
        print("[FEHLER] Build fehlgeschlagen!")
        sys.exit(1)

    # Copy whisper-cpp
    whisper_src = os.path.join(BASE_DIR, "whisper-cpp")
    whisper_dst = os.path.join(DIST_DIR, "whisper-cpp")
    if os.path.isdir(whisper_src):
        print("\n[COPY] Kopiere whisper-cpp...")
        if os.path.exists(whisper_dst):
            shutil.rmtree(whisper_dst)
        shutil.copytree(whisper_src, whisper_dst)
        print(f"  [OK] whisper-cpp kopiert")

    # Copy config
    cfg_src = os.path.join(BASE_DIR, "config.default.yaml")
    cfg_dst = os.path.join(DIST_DIR, "config.default.yaml")
    if os.path.isfile(cfg_src):
        shutil.copy2(cfg_src, cfg_dst)

    # Summary
    total_size = sum(
        os.path.getsize(os.path.join(r, f))
        for r, d, files in os.walk(DIST_DIR)
        for f in files
    )

    print("\n" + "=" * 50)
    print("  VoZii Build abgeschlossen!")
    print("=" * 50)
    print(f"\n  Ordner:  {DIST_DIR}")
    print(f"  Groesse: {total_size / (1024 * 1024):.0f} MB")
    print(f"\n  Starten: VoZii.exe")


if __name__ == "__main__":
    build()
