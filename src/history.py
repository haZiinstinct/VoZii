"""Transkriptions-Historie — die letzten Eintraege lokal als JSON.

Rettet Text, der beim Einfuegen verloren ging (kein Fokus, falsches
Fenster), und macht Diktate ueber das Tray-Menue wieder kopierbar.
Bewusst lokal unter BASE_DIR, abschaltbar via history_enabled.
"""

import json
import logging
import os
import threading
from datetime import datetime

from src.paths import BASE_DIR

log = logging.getLogger(__name__)

HISTORY_LIMIT = 50
HISTORY_PATH = os.path.join(BASE_DIR, "history.json")


class TranscriptionHistory:
    def __init__(self, path: str | None = None, limit: int = HISTORY_LIMIT):
        self._path = path or HISTORY_PATH
        self._limit = limit
        self._lock = threading.Lock()
        self._entries = self._load()

    def _load(self) -> list[dict]:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                valid = [e for e in data
                         if isinstance(e, dict) and isinstance(e.get("text"), str)]
                return valid[-self._limit:]
        except FileNotFoundError:
            pass
        except Exception:
            log.warning("Historie nicht lesbar — starte leer", exc_info=True)
        return []

    def add(self, text: str):
        if not text:
            return
        entry = {"ts": datetime.now().isoformat(timespec="seconds"), "text": text}
        with self._lock:
            self._entries.append(entry)
            self._entries = self._entries[-self._limit:]
            self._save_locked()

    def get_recent(self, n: int = 5) -> list[dict]:
        """Neueste zuerst."""
        with self._lock:
            return list(reversed(self._entries[-n:]))

    def clear(self):
        with self._lock:
            self._entries = []
            self._save_locked()

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def _save_locked(self):
        """Atomar via .tmp + os.replace — nie eine halb geschriebene Datei."""
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._entries, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self._path)
        except Exception:
            log.exception("Historie speichern fehlgeschlagen")
