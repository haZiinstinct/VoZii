"""VoZii Plattform-Abstraktion — Windows / macOS / Linux.

Zentrale Weiche fuer alle plattformspezifischen Operationen, damit der
restliche Code plattformneutral bleibt. Der Windows-Pfad bleibt unveraendert;
macOS/Linux erhalten passende Aequivalente oder stille No-ops.
"""

import logging
import os
import shutil
import subprocess
import sys

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# subprocess.CREATE_NO_WINDOW existiert nur auf Windows. getattr verhindert
# AttributeError, falls der Ausdruck doch auf macOS/Linux ausgewertet wird.
SUBPROCESS_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0


def paste_hotkey() -> tuple[str, str]:
    """Tastenkombination zum Einfuegen: Cmd+V auf macOS, sonst Ctrl+V."""
    if IS_MAC:
        return ("command", "v")
    return ("ctrl", "v")


def open_path(path: str) -> None:
    """Oeffnet eine Datei/URL mit dem Standardprogramm des Systems."""
    try:
        if IS_WINDOWS:
            os.startfile(path)  # type: ignore[attr-defined]
        elif IS_MAC:
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        log.exception("Konnte Pfad nicht oeffnen: %s", path)


# Audio-Feedback. Windows erzeugt per winsound.Beep eine Frequenz; macOS spielt
# kurze System-Sounds (afplay kann keine Toene synthetisieren).
_WIN_TONES = {"start": (600, 80), "done": (880, 60)}
_MAC_SOUNDS = {
    "start": "/System/Library/Sounds/Tink.aiff",
    "done": "/System/Library/Sounds/Pop.aiff",
}


def play_beep(kind: str = "start") -> None:
    """Kurzes akustisches Feedback. kind in {'start', 'done'}."""
    try:
        if IS_WINDOWS:
            import winsound
            freq, dur = _WIN_TONES.get(kind, _WIN_TONES["start"])
            winsound.Beep(freq, dur)
        elif IS_MAC:
            sound = _MAC_SOUNDS.get(kind, _MAC_SOUNDS["start"])
            subprocess.Popen(
                ["afplay", sound],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            # Linux: kein zuverlaessiger einfacher Ton — Terminal-Bell als Best-Effort.
            sys.stdout.write("\a")
            sys.stdout.flush()
    except Exception:
        pass


def whisper_cli_name() -> str:
    """Dateiname der whisper.cpp CLI je Plattform."""
    return "whisper-cli.exe" if IS_WINDOWS else "whisper-cli"


def find_whisper_cli(whisper_dir: str) -> str | None:
    """Sucht die whisper.cpp CLI.

    Reihenfolge:
    1. Gebuendelt neben der App: <whisper_dir>/whisper-cli[.exe]
    2. Auf dem PATH: whisper-cli, dann whisper-cpp (Homebrew-Formel-Name)
    3. macOS: Homebrew-Standardpfade (Apple Silicon + Intel)

    Windows nutzt ausschliesslich das gebuendelte Binary (Verhalten wie bisher).
    """
    bundled = os.path.join(whisper_dir, whisper_cli_name())
    if os.path.isfile(bundled):
        return bundled

    if not IS_WINDOWS:
        for name in ("whisper-cli", "whisper-cpp"):
            found = shutil.which(name)
            if found:
                return found
        if IS_MAC:
            for base in ("/opt/homebrew/bin", "/usr/local/bin"):
                for name in ("whisper-cli", "whisper-cpp"):
                    cand = os.path.join(base, name)
                    if os.path.isfile(cand):
                        return cand
    return None
