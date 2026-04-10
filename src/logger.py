"""VoZii Logging + Single-Instance Lock.

Zentrale Infrastruktur fuer Sichtbarkeit:
- Logging zu Datei (ueberlebt --windowed Mode)
- stdout/stderr Redirect zu os.devnull falls None
- sys.excepthook + threading.excepthook → stumme Exceptions werden geloggt
- Single-Instance via Lock-File mit msvcrt.locking()
"""

import logging
import logging.handlers
import os
import sys
import threading

from src.paths import BASE_DIR

LOG_PATH = os.path.join(BASE_DIR, "vozii.log")
LOCK_PATH = os.path.join(BASE_DIR, "vozii.lock")

# Modul-global: File-Handle fuer den Lock darf nicht GC'd werden
_lock_file = None


def setup_logging() -> None:
    """Konfiguriert logging einmalig fuer die gesamte App."""
    # stdout/stderr Schutz — in --windowed/--onefile sind die None
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    handler = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=1_000_000, backupCount=1, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Alte Handler entfernen (falls setup_logging() mehrfach gerufen wird)
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)

    # Stumme Exceptions einfangen
    def _excepthook(exc_type, exc_value, exc_tb):
        logging.getLogger("uncaught").critical(
            "Uncaught exception", exc_info=(exc_type, exc_value, exc_tb)
        )

    sys.excepthook = _excepthook

    def _thread_excepthook(args):
        logging.getLogger("thread").critical(
            "Uncaught thread exception in %s",
            args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _thread_excepthook


def acquire_single_instance() -> bool:
    """Versucht exklusiven Lock auf vozii.lock zu bekommen.

    Returns:
        True wenn Lock bekommen (wir sind die einzige Instanz).
        False wenn eine andere Instanz bereits laeuft.
    """
    global _lock_file
    try:
        import msvcrt
    except ImportError:
        # Nicht Windows — skip (Dev auf anderem OS)
        return True

    try:
        _lock_file = open(LOCK_PATH, "w")
        msvcrt.locking(_lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        _lock_file.write(str(os.getpid()))
        _lock_file.flush()
        return True
    except OSError:
        # Andere Instanz haelt den Lock
        if _lock_file:
            try:
                _lock_file.close()
            except Exception:
                pass
            _lock_file = None
        return False


def get_log_path() -> str:
    return LOG_PATH
