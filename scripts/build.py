"""VoZii Build — eine einzige standalone .exe."""

import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build():
    print("=" * 40)
    print("  VoZii — Build (Single .exe)")
    print("=" * 40)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",                # EINE .exe
        "--windowed",               # Keine Konsole
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

    exe_path = os.path.join(BASE_DIR, "dist", "VoZii.exe")
    if os.path.isfile(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"\n  Fertig: {exe_path}")
        print(f"  Groesse: {size_mb:.0f} MB")
        print(f"\n  Diese eine Datei an Kollegen schicken!")
        print(f"  whisper-cpp + Modell werden beim ersten Start geladen.")


if __name__ == "__main__":
    build()
