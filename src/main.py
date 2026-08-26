"""VoZii Entry-Point — duenner Launcher, absichtlich nur stdlib-Imports.

Crasht der App-Import (kaputtes LOCALAPPDATA, fehlende DLL, ...), stirbt die
--windowed-Exe sonst voellig stumm. Der Launcher schreibt dann ein Notfall-Log
nach %TEMP% und zeigt einen nativen Dialog (ctypes, kein tkinter — das koennte
selbst die Crash-Ursache sein).
"""

import os
import sys
import tempfile
import traceback

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BOOT_LOG = os.path.join(tempfile.gettempdir(), "vozii_boot_error.log")


def _emergency(exc: BaseException) -> None:
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        with open(BOOT_LOG, "a", encoding="utf-8") as f:
            f.write(detail + "\n")
    except OSError:
        pass
    try:
        import ctypes
        # zweisprachig: an dieser Stelle ist i18n evtl. gar nicht ladbar
        ctypes.windll.user32.MessageBoxW(
            None,
            "VoZii konnte nicht starten / VoZii failed to start.\n\n"
            f"{type(exc).__name__}: {exc}\n\nLog: {BOOT_LOG}",
            "VoZii", 0x10,  # MB_ICONERROR
        )
    except Exception:
        pass


def main():
    try:
        from src.app import run
        run()
    except (SystemExit, KeyboardInterrupt):
        raise
    except BaseException as e:
        _emergency(e)


if __name__ == "__main__":
    main()
