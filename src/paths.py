"""Pfad-Aufloesung — funktioniert in Dev, --onedir UND --onefile Modus."""

import os
import sys


def get_base_dir() -> str:
    """Gibt das Verzeichnis zurueck wo config.yaml und whisper-cpp/ liegen.
    - Dev: Projektordner (parent von src/)
    - PyInstaller --onedir: Ordner mit VoZii.exe
    - PyInstaller --onefile: Ordner mit VoZii.exe (NICHT der Temp-Ordner)
    """
    if getattr(sys, "frozen", False):
        # .exe Modus — immer der Ordner wo die .exe liegt
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BASE_DIR = get_base_dir()
