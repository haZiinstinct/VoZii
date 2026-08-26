"""Stiller Update-Check gegen GitHub Releases.

Ein einziger API-Call pro App-Start (Opt-out via Config-Key update_check);
jeder Fehler — offline, Rate-Limit, Timeout, Muell-Antwort — bleibt still.
"""

import json
import logging
import threading
import urllib.request

log = logging.getLogger(__name__)

RELEASES_API = "https://api.github.com/repos/haZiinstinct/VoZii/releases/latest"
RELEASES_PAGE = "https://github.com/haZiinstinct/VoZii/releases/latest"


def fetch_latest_version(timeout: float = 4.0) -> str | None:
    """Neueste Release-Version ("1.8.0", ohne "v") oder None bei jedem Fehler."""
    try:
        req = urllib.request.Request(
            RELEASES_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "VoZii"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = (data.get("tag_name") or "").strip()
        return tag.lstrip("v") or None
    except Exception as e:
        log.debug("Update-Check fehlgeschlagen: %s", e)
        return None


def is_newer(latest: str, current: str) -> bool:
    """Toleranter Versionsvergleich — Muell-Tags gelten nie als neuer."""
    def parts(v):
        try:
            return [int(p) for p in v.strip().lstrip("v").split(".")]
        except (ValueError, AttributeError):
            return None

    lat, cur = parts(latest), parts(current)
    if lat is None or cur is None:
        return False
    return lat > cur


def check_async(current: str, on_update) -> None:
    """Daemon-Thread; ruft on_update(latest) NUR bei echt neuerer Version."""
    def run():
        latest = fetch_latest_version()
        if latest and is_newer(latest, current):
            log.info("Update verfuegbar: %s (installiert: %s)", latest, current)
            on_update(latest)

    threading.Thread(target=run, daemon=True, name="update-check").start()
