"""Pfad-Aufloesung — schreibbarer Fallback auf %LOCALAPPDATA%.

Funktioniert in Dev-Modus, --onedir UND --onefile Modus. Wenn der
Ordner neben der .exe nicht schreibbar ist (z.B. C:\\Program Files\\),
faellt auf %LOCALAPPDATA%\\VoZii zurueck.
"""

import os
import sys


def _exe_dir() -> str:
    """Ordner wo die .exe liegt (oder Projekt-Root im Dev-Modus)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _is_writable(path: str) -> bool:
    """Prueft ob ein Verzeichnis beschreibbar ist."""
    try:
        test_file = os.path.join(path, ".vozii_write_test")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        return True
    except Exception:
        return False


def _appdata_dir() -> str:
    """Fallback: %LOCALAPPDATA%\\VoZii (immer schreibbar)."""
    local_appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.vozii")
    path = os.path.join(local_appdata, "VoZii")
    os.makedirs(path, exist_ok=True)
    return path


def get_base_dir() -> str:
    """Schreibbarer Verzeichnis fuer config, logs, whisper-cpp, etc."""
    exe_dir = _exe_dir()
    if _is_writable(exe_dir):
        return exe_dir
    return _appdata_dir()


BASE_DIR = get_base_dir()
