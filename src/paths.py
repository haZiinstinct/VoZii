"""Central path resolution — works in dev mode AND as PyInstaller .exe."""

import os
import sys


def get_base_dir() -> str:
    """Return the project root directory.
    - Dev mode: parent of src/
    - PyInstaller: directory containing VoiceToText.exe
    """
    if getattr(sys, "frozen", False):
        # Running as PyInstaller bundle
        return os.path.dirname(sys.executable)
    else:
        # Running as script: src/ -> project root
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BASE_DIR = get_base_dir()
