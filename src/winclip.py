"""Win32-Zwischenablage mit Retry + Ctrl+V per SendInput.

Warum nicht pyperclip/pyautogui:

- Die Zwischenablage ist eine *globale* Systemressource. Jede andere App
  (Office, Teams, RDP, Clipboard-Manager) kann sie kurz exklusiv halten;
  OpenClipboard schlaegt dann fehl. pyperclip wirft in dem Moment sofort —
  ueber lange Sessions genau das "kopiert auf einmal nicht mehr"-Symptom.
  Hier wird stattdessen ein paar hundert Millisekunden lang neu versucht.
- pyautogui prueft vor *jedem* Tastendruck die Mausposition und wirft eine
  FailSafeException, sobald der Zeiger in einer Bildschirmecke steht. Das
  hat real dazu gefuehrt, dass Diktate nur in der Zwischenablage landeten.

Alles still no-op ausserhalb von Windows.
"""

import ctypes
import logging
import sys
import time
from ctypes import wintypes

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002

# OpenClipboard-Retry: Windows-Empfehlung sind mehrere kurze Versuche.
# 40 x 25 ms = 1 s Geduld, ohne den Worker-Thread spuerbar zu blockieren.
_OPEN_ATTEMPTS = 40
_OPEN_DELAY_S = 0.025

if IS_WINDOWS:
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32

    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.CloseClipboard.argtypes = []
    _user32.CloseClipboard.restype = wintypes.BOOL
    _user32.EmptyClipboard.argtypes = []
    _user32.EmptyClipboard.restype = wintypes.BOOL
    _user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    _user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    _user32.GetClipboardData.argtypes = [wintypes.UINT]
    _user32.GetClipboardData.restype = wintypes.HANDLE
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.SetClipboardData.restype = wintypes.HANDLE
    _user32.GetClipboardSequenceNumber.argtypes = []
    _user32.GetClipboardSequenceNumber.restype = wintypes.DWORD

    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    _kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalFree.restype = wintypes.HGLOBAL
    _kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalLock.restype = wintypes.LPVOID
    _kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalUnlock.restype = wintypes.BOOL
    _kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalSize.restype = ctypes.c_size_t

    _user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    _user32.MapVirtualKeyW.restype = wintypes.UINT


class _Clipboard:
    """Context-Manager: oeffnet die Zwischenablage mit Retry, schliesst garantiert.

    `opened` sagt, ob es geklappt hat — der Aufrufer entscheidet dann, ob er
    aufgibt oder es spaeter erneut versucht.
    """

    def __init__(self, attempts: int = _OPEN_ATTEMPTS):
        self.attempts = attempts
        self.opened = False

    def __enter__(self):
        for _ in range(self.attempts):
            if _user32.OpenClipboard(None):
                self.opened = True
                return self
            time.sleep(_OPEN_DELAY_S)
        log.warning("Zwischenablage nach %d Versuchen belegt (andere App haelt sie)",
                    self.attempts)
        return self

    def __exit__(self, *_exc):
        if self.opened:
            _user32.CloseClipboard()
        return False


def sequence_number() -> int:
    """Zaehler, den Windows bei jeder Aenderung der Zwischenablage hochzaehlt.

    Braucht kein OpenClipboard und ist damit der einzige Weg, eine Aenderung
    zu erkennen, ohne selbst mit anderen Apps um die Ablage zu konkurrieren.
    """
    if not IS_WINDOWS:
        return 0
    try:
        return int(_user32.GetClipboardSequenceNumber())
    except Exception:
        return 0


def get_text() -> str | None:
    """Text aus der Zwischenablage. None = nicht lesbar oder kein Text drin."""
    if not IS_WINDOWS:
        return _fallback_paste()
    try:
        if not _user32.IsClipboardFormatAvailable(_CF_UNICODETEXT):
            return None
        with _Clipboard() as clip:
            if not clip.opened:
                return None
            handle = _user32.GetClipboardData(_CF_UNICODETEXT)
            if not handle:
                return None
            ptr = _kernel32.GlobalLock(handle)
            if not ptr:
                return None
            try:
                return ctypes.c_wchar_p(ptr).value
            finally:
                _kernel32.GlobalUnlock(handle)
    except Exception:
        log.debug("Zwischenablage lesen fehlgeschlagen", exc_info=True)
        return None


def set_text(text: str) -> bool:
    """Text in die Zwischenablage legen. Returns True bei Erfolg."""
    if not IS_WINDOWS:
        return _fallback_copy(text)
    try:
        data = text + "\0"
        size = len(data) * ctypes.sizeof(ctypes.c_wchar)
        handle = _kernel32.GlobalAlloc(_GMEM_MOVEABLE, size)
        if not handle:
            return False
        ptr = _kernel32.GlobalLock(handle)
        if not ptr:
            _kernel32.GlobalFree(handle)
            return False
        ctypes.memmove(ptr, ctypes.create_unicode_buffer(data), size)
        _kernel32.GlobalUnlock(handle)

        with _Clipboard() as clip:
            if not clip.opened:
                _kernel32.GlobalFree(handle)
                return False
            _user32.EmptyClipboard()
            # Ab hier gehoert das Handle dem System — kein GlobalFree mehr
            if not _user32.SetClipboardData(_CF_UNICODETEXT, handle):
                _kernel32.GlobalFree(handle)
                return False
        return True
    except Exception:
        log.exception("Zwischenablage schreiben fehlgeschlagen")
        return False


def _fallback_paste() -> str | None:
    try:
        import pyperclip
        return pyperclip.paste()
    except Exception:
        return None


def _fallback_copy(text: str) -> bool:
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        return False


# --- Tastatureingabe (SendInput) ---

_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_VK_CONTROL = 0x11
_VK_V = 0x56


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUTUNION(ctypes.Union):
    # MOUSEINPUT ist das groesste Union-Mitglied — mitdefinieren, damit ctypes
    # die Struktur genauso gross macht wie Windows sie erwartet
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


if IS_WINDOWS:
    _user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
    _user32.SendInput.restype = wintypes.UINT


def _key_input(vk: int, key_up: bool) -> _INPUT:
    scan = _user32.MapVirtualKeyW(vk, 0) if IS_WINDOWS else 0
    flags = _KEYEVENTF_KEYUP if key_up else 0
    return _INPUT(type=_INPUT_KEYBOARD,
                  u=_INPUTUNION(ki=_KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags,
                                               time=0, dwExtraInfo=0)))


def send_ctrl_v() -> bool:
    """Ctrl+V an das Fenster im Vordergrund. Returns True bei Erfolg.

    False heisst: Windows hat die Eingabe abgelehnt — praktisch immer UIPI,
    also ein Zielfenster mit hoeheren Rechten (als Admin gestartete App).
    """
    if not IS_WINDOWS:
        return False
    events = (_INPUT * 4)(
        _key_input(_VK_CONTROL, False),
        _key_input(_VK_V, False),
        _key_input(_VK_V, True),
        _key_input(_VK_CONTROL, True),
    )
    try:
        sent = _user32.SendInput(len(events), events, ctypes.sizeof(_INPUT))
        if sent != len(events):
            log.error("SendInput hat nur %d von %d Events akzeptiert (Fehler %d) — "
                      "Zielfenster laeuft vermutlich als Administrator",
                      sent, len(events), _kernel32.GetLastError())
            return False
        return True
    except Exception:
        log.exception("SendInput fehlgeschlagen")
        return False


def modifiers_held() -> bool:
    """Haelt der Nutzer gerade Shift/Ctrl/Alt/Win?

    Aus einem programmatischen Ctrl+V wuerde sonst z. B. Ctrl+Shift+V —
    in vielen Apps eine voellig andere Funktion.
    """
    if not IS_WINDOWS:
        return False
    try:
        get_state = _user32.GetAsyncKeyState
        return any(get_state(vk) & 0x8000 for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C))
    except Exception:
        return False
