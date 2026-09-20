"""Text an der Cursor-Position einfuegen — Modifier-Wait + Clipboard-Restore.

Zwischenablage und Tastendruck laufen ueber src.winclip (Win32 mit Retry),
nicht ueber pyperclip/pyautogui: beide brechen in genau den Situationen ab,
die ueber lange Sessions unvermeidlich auftreten (Ablage kurz von einer
anderen App belegt, Mauszeiger in der Bildschirmecke).
"""

import logging
import threading
import time

from src import winclip

log = logging.getLogger(__name__)

_MODIFIER_WAIT_S = 1.0
# Zeit, die Windows braucht, bis unser Text wirklich in der Ablage steht und
# das Zielfenster ihn lesen kann.
_CLIPBOARD_SETTLE_S = 0.15
# Grosszuegig: die Ziel-App liest die Zwischenablage erst, wenn sie das
# Ctrl+V verarbeitet. Unter Last (Browser, Electron-Apps) dauert das leicht
# eine Sekunde — wird zu frueh zurueckgesetzt, fuegt die App den ALTEN
# Inhalt ein. Der Restore laeuft daher im Hintergrund und blockiert nichts.
_RESTORE_DELAY_S = 1.5
# set_text + Gegenprobe; scheitert beides, ist die Ablage dauerhaft belegt
_COPY_ATTEMPTS = 3


def _wait_for_modifier_release(timeout_s: float = _MODIFIER_WAIT_S) -> bool:
    """Wartet bis der Nutzer die Hotkey-Tasten losgelassen hat.

    Haelt er z.B. Ctrl+Shift+Space noch, wuerde aus dem programmatischen
    Ctrl+V ein Ctrl+Shift+V — in vielen Apps eine andere Funktion.
    Returns False, wenn nach timeout_s immer noch etwas gehalten wird.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not winclip.modifiers_held():
            return True
        time.sleep(0.02)
    return False


def _copy_verified(text: str) -> bool:
    """Text in die Ablage legen UND gegenpruefen, dass er dort steht.

    Ohne die Gegenprobe wuerde bei belegter Ablage ein Ctrl+V gesendet, das
    den *vorherigen* Inhalt einfuegt — schlimmer als gar nichts zu tun.
    """
    for attempt in range(_COPY_ATTEMPTS):
        if winclip.set_text(text):
            time.sleep(_CLIPBOARD_SETTLE_S)
            if winclip.get_text() == text:
                return True
        log.warning("Zwischenablage-Schreibversuch %d/%d fehlgeschlagen",
                    attempt + 1, _COPY_ATTEMPTS)
        time.sleep(0.1)
    return False


def _restore_later(previous: str, ours: str, delay_s: float = _RESTORE_DELAY_S):
    """Stellt die alte Zwischenablage zeitversetzt wieder her.

    Nur wenn unser Text noch drin liegt — sonst hat entweder der Nutzer
    inzwischen etwas anderes kopiert oder das naechste Diktat ist schon da.
    """
    def run():
        time.sleep(delay_s)
        try:
            if winclip.get_text() == ours:
                winclip.set_text(previous)
        except Exception:
            log.debug("Clipboard-Restore fehlgeschlagen", exc_info=True)

    threading.Thread(target=run, daemon=True, name="clipboard-restore").start()


def insert_text(text: str, restore_clipboard: bool = True) -> bool:
    """Text an Cursorposition einfuegen. Returns True bei Erfolg.

    Bei Erfolg wird die vorherige Zwischenablage wiederhergestellt
    (restore_clipboard); bei Misserfolg bleibt der Text drin als Fallback
    und der Caller informiert den Nutzer (Overlay 'CLIP').
    """
    if not text:
        return True

    previous = winclip.get_text() if restore_clipboard else None

    if not _copy_verified(text):
        log.error("Text nicht in die Zwischenablage schreibbar — kein Einfuegen")
        return False

    if not _wait_for_modifier_release():
        # Ctrl/Shift/Alt noch gehalten: ein Ctrl+V daraus wuerde in der
        # Ziel-App etwas anderes ausloesen. Text liegt in der Ablage, der
        # Nutzer fuegt selbst ein.
        log.warning("Modifier nach %.1fs noch gedrueckt — Text bleibt in der "
                    "Zwischenablage", _MODIFIER_WAIT_S)
        return False

    if not winclip.send_ctrl_v():
        log.error("Einfuegen fehlgeschlagen — Text bleibt in der Zwischenablage")
        return False

    if restore_clipboard and previous:
        _restore_later(previous, text)
    return True
