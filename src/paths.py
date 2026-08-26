"""Pfad-Aufloesung — Daten liegen in %LOCALAPPDATA%\\VoZii.

Funktioniert in Dev-Modus, --onedir UND --onefile Modus.

Bestandsnutzer-Migration: Wenn neben der .exe bereits Daten liegen
(config.yaml oder whisper-cpp/), wird der Exe-Ordner weiterverwendet —
nichts wird verschoben. Neuinstallationen landen immer in
%LOCALAPPDATA%\\VoZii, damit keine 1,5-GB-Modelle in Downloads/OneDrive
liegen.
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


def _has_existing_data(path: str) -> bool:
    """Liegen neben der Exe bereits VoZii-Daten (Bestandsnutzer)?"""
    return (
        os.path.isfile(os.path.join(path, "config.yaml"))
        or os.path.isdir(os.path.join(path, "whisper-cpp"))
    )


def _appdata_dir() -> str:
    """%LOCALAPPDATA%\\VoZii (immer schreibbar)."""
    local_appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.vozii")
    path = os.path.join(local_appdata, "VoZii")
    os.makedirs(path, exist_ok=True)
    return path


# Grund, falls die normale Aufloesung scheiterte — setup_logging() loggt das
# als WARNING (frueher gab es hier nur einen stummen Tod der --windowed-Exe)
BASE_DIR_FALLBACK = None


def get_base_dir() -> str:
    """Schreibbares Verzeichnis fuer config, logs, whisper-cpp, etc.

    Darf niemals werfen — laeuft auf Import-Ebene, vor jedem Logging."""
    global BASE_DIR_FALLBACK
    try:
        exe_dir = _exe_dir()
        if _has_existing_data(exe_dir) and _is_writable(exe_dir):
            return exe_dir
    except Exception as e:
        BASE_DIR_FALLBACK = f"exe_dir unbrauchbar: {e}"
    try:
        return _appdata_dir()
    except Exception as e:
        # LOCALAPPDATA umgeleitet/gesperrt (kaputtes Roaming-Profil o. ae.)
        BASE_DIR_FALLBACK = f"LOCALAPPDATA unbrauchbar: {e}"
        import tempfile
        path = os.path.join(tempfile.gettempdir(), "VoZii")
        os.makedirs(path, exist_ok=True)
        return path


BASE_DIR = get_base_dir()

# Eigener Temp-Ordner fuer Aufnahme-WAVs — wird beim App-Start geleert,
# damit sich keine Altlasten in %TEMP% ansammeln.
TMP_DIR = os.path.join(BASE_DIR, "tmp")
