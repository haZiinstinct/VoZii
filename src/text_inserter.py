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
# Kurze Pause nur bei Retry (wenn ein anderer Clipboard-Monitor funkt).
# Auf dem Normalpfad ist SetClipboardData + CloseClipboard unter Win32 synchron —
# sofortiges Gegenpruefen spart ~150 ms bei jedem einzelnen Diktat.
_CLIPBOARD_RETRY_S = 0.05
# Grosszuegig: die Ziel-App liest die Zwischenablage erst, wenn sie das
# Ctrl+V verarbeitet. Unter Last (Browser, Electron-Apps) dauert das leicht
# eine Sekunde — wird zu frueh zurueckgesetzt, fuegt die App den ALTEN
# Inhalt ein. Der Restore laeuft daher im Hintergrund und blockiert nichts.
_RESTORE_DELAY_S = 1.5
# set_text + Gegenprobe; scheitert beides, ist die Ablage dauerhaft belegt
_COPY_ATTEMPTS = 3

# Merkt sich einen noch ausstehenden Restore fuer schnelle Doppel-Diktate
# innerhalb von _RESTORE_DELAY_S: das zweite Diktat rettet sonst den Text des
# ersten statt der urspruenglichen Zwischenablage.
_restore_lock = threading.Lock()
_restore_gen = 0
_pending_restore: dict | None = None


def _set_clip(text: str, private: bool = False) -> bool:
    """Ruft winclip.set_text auf — tolerant gegenueber 1-Arg-Mocks in Tests."""
    if not private:
        return winclip.set_text(text)
    try:
        return winclip.set_text(text, private=True)
    except TypeError:
        return winclip.set_text(text)


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


def _copy_verified(text: str, private: bool = False) -> bool:
    """Text in die Ablage legen UND gegenpruefen, dass er dort steht.

    Ohne die Gegenprobe wuerde bei belegter Ablage ein Ctrl+V gesendet, das
    den *vorherigen* Inhalt einfuegt — schlimmer als gar nichts zu tun.
    """
    for attempt in range(_COPY_ATTEMPTS):
        if _set_clip(text, private=private):
            if winclip.get_text() == text:
                return True
            time.sleep(_CLIPBOARD_RETRY_S)
            if winclip.get_text() == text:
                return True
        log.warning("Zwischenablage-Schreibversuch %d/%d fehlgeschlagen",
                    attempt + 1, _COPY_ATTEMPTS)
        time.sleep(_CLIPBOARD_RETRY_S)
    return False


def _restore_later(previous: str, ours: str, delay_s: float = _RESTORE_DELAY_S,
                   expected_seq: int = 0):
    """Stellt die alte Zwischenablage zeitversetzt wieder her.

    Nur wenn seit unserem Schreiben niemand die Ablage angefasst hat
    (sequence_number ohne OpenClipboard-Konflikt; Fallback get_text == ours).
    """
    global _restore_gen, _pending_restore
    with _restore_lock:
        _restore_gen += 1
        gen = _restore_gen
        _pending_restore = {"previous": previous, "ours": ours, "seq": expected_seq}

    def run():
        global _pending_restore
        time.sleep(delay_s)
        with _restore_lock:
            if gen != _restore_gen:
                return  # inzwischen neueres Diktat -> uebernimmt den Restore
            _pending_restore = None
        try:
            if expected_seq:
                if winclip.sequence_number() == expected_seq:
                    _set_clip(previous, private=True)
            elif winclip.get_text() == ours:
                _set_clip(previous, private=True)
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

    previous = None
    if restore_clipboard:
        with _restore_lock:
            pending = _pending_restore
        cur_seq = winclip.sequence_number()
        if pending and ((pending["seq"] and cur_seq == pending["seq"])
                        or (not pending["seq"] and winclip.get_text() == pending["ours"])):
            # Vorheriger Restore steht noch aus -> urspruenglichen Inhalt retten
            previous = pending["previous"]
        else:
            previous = winclip.get_text()

    # Wenn die Ablage nach dem Einfuegen wiederhergestellt wird, unseren
    # temporaeren Text aus Windows-11-Verlauf (Win+V) und Cloud-Sync heraushalten
    if not _copy_verified(text, private=restore_clipboard):
        log.error("Text nicht in die Zwischenablage schreibbar — kein Einfuegen")
        return False

    seq_after_set = winclip.sequence_number()

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
        try:
            _restore_later(previous, text, expected_seq=seq_after_set)
        except TypeError:
            # Kompatibel mit 2/3-Arg-Test-Mocks fuer _restore_later
            _restore_later(previous, text)
    return True
