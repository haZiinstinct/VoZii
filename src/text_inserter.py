"""Text an der Cursor-Position einfuegen — Modifier-Wait + Clipboard-Restore."""

import ctypes
import logging
import time

import pyautogui
import pyperclip

log = logging.getLogger(__name__)

# Modifier, die das programmatische Ctrl+V verfaelschen wuerden:
# Shift, Ctrl, Alt, LWin, RWin
_MODIFIER_VKS = (0x10, 0x11, 0x12, 0x5B, 0x5C)
_MODIFIER_WAIT_S = 1.0
# Etwas grosszuegiger: gerade das erste Einfuegen (Ziel-App noch nicht fokussiert)
# ist langsam — sonst wird die Zwischenablage zu frueh wiederhergestellt und die
# App fuegt den ALTEN Inhalt ein.
_CLIPBOARD_SETTLE_S = 0.2
_RESTORE_DELAY_S = 0.6


def _wait_for_modifier_release(timeout_s: float = _MODIFIER_WAIT_S):
    """Wartet bis der Nutzer die Hotkey-Tasten losgelassen hat.

    Haelt er z.B. Ctrl+Shift+Space noch, wuerde aus dem programmatischen
    Ctrl+V ein Ctrl+Shift+V — in vielen Apps eine andere Funktion.
    """
    try:
        get_state = ctypes.windll.user32.GetAsyncKeyState
    except Exception:
        time.sleep(0.05)
        return
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not any(get_state(vk) & 0x8000 for vk in _MODIFIER_VKS):
            return
        time.sleep(0.02)
    log.warning("Modifier nach %.1fs noch gedrueckt — fuege trotzdem ein", timeout_s)


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
        try:
            previous = pyperclip.paste()
        except Exception:
            previous = None

    pyperclip.copy(text)
    _wait_for_modifier_release()
    time.sleep(_CLIPBOARD_SETTLE_S)

    try:
        pyautogui.hotkey("ctrl", "v")
    except Exception:
        log.exception("Einfuegen fehlgeschlagen — Text bleibt in der Zwischenablage")
        return False

    if restore_clipboard and previous:
        time.sleep(_RESTORE_DELAY_S)
        try:
            # Nur wiederherstellen, wenn unser Text noch in der Zwischenablage
            # liegt — sonst hat die App ihn evtl. noch nicht eingefuegt oder
            # der Nutzer hat schon was anderes kopiert.
            if pyperclip.paste() == text:
                pyperclip.copy(previous)
        except Exception:
            log.debug("Clipboard-Restore fehlgeschlagen", exc_info=True)
    return True
