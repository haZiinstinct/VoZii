"""VoZii Build — standalone .exe ohne sichtbare Konsole."""

import os
import shutil
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(BASE_DIR, "dist", "VoZii")


def build():
    print("=" * 40)
    print("  VoZii — Build")
    print("=" * 40)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--onedir", "--windowed",
        "--name", "VoZii",
        "--icon", os.path.join(BASE_DIR, "src", "vozii.ico"),
        "--add-data", f"{os.path.join(BASE_DIR, 'config.default.yaml')};.",
        "--hidden-import", "pynput.keyboard._win32",
        "--hidden-import", "pynput.mouse._win32",
        "--hidden-import", "PIL._tkinter_finder",
        "--collect-submodules", "pynput",
        "--collect-all", "customtkinter",
        os.path.join(BASE_DIR, "src", "main.py"),
    ]

    result = subprocess.run(cmd, cwd=BASE_DIR)
    if result.returncode != 0:
        print("[FEHLER] Build fehlgeschlagen!")
        sys.exit(1)

    # Config kopieren
    for f in ("config.default.yaml",):
        src = os.path.join(BASE_DIR, f)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(DIST_DIR, f))

    # whisper-cpp kopieren wenn vorhanden (optional fuer Entwickler)
    whisper_src = os.path.join(BASE_DIR, "whisper-cpp")
    whisper_dst = os.path.join(DIST_DIR, "whisper-cpp")
    if os.path.isdir(whisper_src):
        if os.path.exists(whisper_dst):
            shutil.rmtree(whisper_dst)
        shutil.copytree(whisper_src, whisper_dst)

    size = sum(os.path.getsize(os.path.join(r, f))
               for r, _, fs in os.walk(DIST_DIR) for f in fs)

    print(f"\n  Fertig: {DIST_DIR}")
    print(f"  Groesse: {size // 1048576} MB")
    print(f"  Starten: VoZii.exe")


if __name__ == "__main__":
    build()
