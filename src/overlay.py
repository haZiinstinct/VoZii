"""VoZii Recording-Overlay — folgt dem Monitor mit dem Mauszeiger.

Raw tkinter (kein zweites Tray-Icon). Abgerundete Ecken via
-transparentcolor-Trick, Status-Codes statt nur 'ERR'.
"""

import ctypes
import logging
import threading
import tkinter as tk
from ctypes import wintypes
from tkinter import font as tkfont

from src.i18n import t
from src.state import AppState
from src.theme import BRAND, FONT_MONO

log = logging.getLogger(__name__)

# Animation frames fuer Transcribing-State (wechsel alle 300ms)
TRANSCRIBING_FRAMES = ["·", "· ·", "· · ·", "· ·"]
ANIMATION_INTERVAL_MS = 300

# Diese Farbe wird per -transparentcolor ausgestanzt -> runde Ecken
_TRANSPARENT = "#000001"
_MARGIN = 16
_HEIGHT = 28
# Semantischer Flash-Key -> (i18n-Text-Key, Farbe). Trennt Anzeige (uebersetzbar)
# von der Farb-Logik, die unabhaengig von der Sprache stabil bleibt.
_FLASH = {
    "clip": ("overlay.clip", "cyan"),        # Text in der Zwischenablage (Einfuegen ging nicht)
    "short": ("overlay.short", "amber"),     # Aufnahme zu kurz
    "empty": ("overlay.empty", "amber"),     # nichts erkannt
    "ready": ("overlay.ready", "green"),     # First-Run-Hinweis
    "err_mic": ("overlay.err_mic", "red"),
    "err_whisper": ("overlay.err_whisper", "red"),
}


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class RecordingOverlay:
    """Minimales Overlay — Canvas mit abgerundetem Hintergrund + Statustext."""

    def __init__(self):
        self._thread = None
        self._root = None
        self._canvas = None
        self._bg_id = None
        self._dot_id = None
        self._text_id = None
        self._ready = threading.Event()
        self._anim_frame = 0
        self._anim_active = False
        self._flash_job = None
        self._scale = 1.0

    @property
    def is_alive(self) -> bool:
        return self._root is not None and self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Startet den Overlay-Thread. False wenn das Overlay nicht hochkommt —
        Caller laeuft dann ohne Overlay weiter (statt mit totem Objekt)."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=3) or self._root is None:
            log.error("Overlay-Thread nicht initialisiert — weiter ohne Overlay")
            return False
        return True

    def _run(self):
        try:
            self._root = tk.Tk()
        except Exception:
            log.exception("Overlay: Tk-Init fehlgeschlagen")
            self._root = None
            self._ready.set()
            return
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.92)
        try:
            self._root.attributes("-toolwindow", True)
        except tk.TclError:
            pass

        # Hintergrundfarbe ausstanzen -> abgerundete Ecken. Wenn die Plattform
        # das nicht kann: eckig mit Card-Farbe.
        self._root.configure(bg=_TRANSPARENT)
        try:
            self._root.attributes("-transparentcolor", _TRANSPARENT)
        except tk.TclError:
            self._root.configure(bg=BRAND["card"])

        # High-DPI: Geometrie skalieren (Fonts in pt skalieren von selbst)
        try:
            self._scale = max(1.0, self._root.winfo_fpixels("1i") / 96.0)
        except Exception:
            self._scale = 1.0

        h = self._px(_HEIGHT)
        self._canvas = tk.Canvas(self._root, width=self._px(110), height=h,
                                 bg=_TRANSPARENT, highlightthickness=0)
        self._canvas.pack()
        self._dot_id = self._canvas.create_text(
            self._px(16), h // 2, text="●", font=(FONT_MONO, 9), fill=BRAND["red"])
        self._text_id = self._canvas.create_text(
            self._px(26), h // 2, text="REC", anchor="w",
            font=(FONT_MONO, 10, "bold"), fill=BRAND["red"])
        self._layout("REC")

        self._root.withdraw()
        self._ready.set()
        self._root.mainloop()

    def _px(self, logical: int) -> int:
        return int(logical * self._scale)

    def _round_rect(self, x1, y1, x2, y2, r, **kwargs):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
               x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self._canvas.create_polygon(pts, smooth=True, **kwargs)

    def _layout(self, text: str):
        """Passt Canvas-Breite an den Text an und zeichnet den Hintergrund neu."""
        # Echte gerenderte Ausdehnung statt Font.measure() — measure weicht auf
        # High-DPI minimal vom tatsaechlich gezeichneten Text ab (Punkte ragten raus).
        bbox = self._canvas.bbox(self._dot_id, self._text_id)
        if bbox:
            w = bbox[2] + self._px(16)
        else:
            f = tkfont.Font(family=FONT_MONO, size=10, weight="bold")
            w = self._px(26) + f.measure(text) + self._px(16)
        h = self._px(_HEIGHT)
        self._canvas.configure(width=w, height=h)
        if self._bg_id is not None:
            self._canvas.delete(self._bg_id)
        self._bg_id = self._round_rect(0, 0, w, h, self._px(13), fill=BRAND["card"])
        self._canvas.tag_lower(self._bg_id)
        self._root.geometry(f"{w}x{h}")
        self._position(w, h)

    def _position(self, w: int, h: int):
        """Unten rechts auf dem Monitor, auf dem der Mauszeiger steht."""
        x = y = None
        try:
            pt = wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            mon = ctypes.windll.user32.MonitorFromPoint(pt, 2)  # MONITOR_DEFAULTTONEAREST
            info = _MONITORINFO()
            info.cbSize = ctypes.sizeof(_MONITORINFO)
            if ctypes.windll.user32.GetMonitorInfoW(mon, ctypes.byref(info)):
                work = info.rcWork
                x = work.right - w - self._px(_MARGIN)
                y = work.bottom - h - self._px(_MARGIN)
        except Exception:
            pass
        if x is None:
            x = self._root.winfo_screenwidth() - w - self._px(_MARGIN)
            y = self._root.winfo_screenheight() - h - self._px(60)
        self._root.geometry(f"+{x}+{y}")

    # --- Thread-sichere API (alles via root.after auf den Tk-Thread) ---

    def update_state(self, state):
        if not self._root: return
        self._root.after(0, lambda: self._apply(state))

    def flash(self, key: str, duration_ms: int = 5000, **fmt):
        """Zeigt einen Status (semantischer Key, z.B. 'clip', 'err_mic', 'ready')
        und blendet nach duration_ms wieder aus. fmt fuellt Platzhalter (hotkey)."""
        if not self._root: return
        self._root.after(0, lambda: self._show_flash(key, duration_ms, fmt))

    def stop(self):
        self._anim_active = False
        if self._root:
            try:
                self._root.after(0, self._root.destroy)
            except Exception as e:
                log.warning("Overlay destroy failed: %s", e)
        # Auf das Ende der mainloop warten, damit der Prozess deterministisch endet
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)

    # --- Implementierung (laeuft im Tk-Thread) ---

    def _cancel_flash(self):
        if self._flash_job is not None:
            try:
                self._root.after_cancel(self._flash_job)
            except Exception:
                pass
            self._flash_job = None

    def _set_content(self, text: str, color: str):
        self._canvas.itemconfigure(self._dot_id, fill=color)
        self._canvas.itemconfigure(self._text_id, text=text, fill=color)
        self._layout(text)

    def _apply(self, state):
        if not self._root: return
        self._cancel_flash()
        if state == AppState.RECORDING:
            self._anim_active = False
            self._set_content(t("overlay.rec"), BRAND["red"])
            self._root.deiconify()
        elif state == AppState.TRANSCRIBING:
            # Feld auf den breitesten Animations-Frame dimensionieren, damit die
            # Punkte waehrend der Animation nicht aus dem Kasten ragen
            self._set_content(max(TRANSCRIBING_FRAMES, key=len), BRAND["cyan"])
            self._root.deiconify()
            if not self._anim_active:
                self._anim_active = True
                self._anim_frame = 0
                self._animate_step()
        else:
            self._anim_active = False
            self._root.withdraw()

    def _animate_step(self):
        """Animiert die Dots waehrend TRANSCRIBING."""
        if not self._anim_active or not self._root:
            return
        frame = TRANSCRIBING_FRAMES[self._anim_frame % len(TRANSCRIBING_FRAMES)]
        self._canvas.itemconfigure(self._text_id, text=frame)
        self._anim_frame += 1
        self._root.after(ANIMATION_INTERVAL_MS, self._animate_step)

    def _show_flash(self, key: str, duration_ms: int, fmt: dict):
        if not self._root: return
        self._anim_active = False
        self._cancel_flash()
        text_key, color_name = _FLASH.get(key, (None, "red"))
        text = t(text_key, **fmt) if text_key else key
        color = BRAND.get(color_name, BRAND["red"])
        self._set_content(text, color)
        self._root.deiconify()
        self._flash_job = self._root.after(duration_ms, self._end_flash)

    def _end_flash(self):
        self._flash_job = None
        if self._root:
            self._root.withdraw()
