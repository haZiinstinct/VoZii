"""VoZii Recording-Overlay — folgt dem Monitor mit dem Mauszeiger.

Raw tkinter (kein zweites Tray-Icon). Abgerundete Ecken via
-transparentcolor-Trick, Status-Codes statt nur 'ERR'.
"""

import ctypes
import logging
import os
import threading
import time
import tkinter as tk
from ctypes import wintypes
from tkinter import font as tkfont

from src.i18n import is_rtl, t
from src.state import AppState
from src.theme import BRAND, FONT_BODY, FONT_MONO
from src.winutil import monitor_dpi_scale

log = logging.getLogger(__name__)

# Animation frames fuer Transcribing-State (wechsel alle 300ms)
TRANSCRIBING_FRAMES = ["·", "· ·", "· · ·", "· ·"]
ANIMATION_INTERVAL_MS = 300
# Aufnahme-Timer + subtiler Live-Pegel im Overlay (nur waehrend RECORDING)
_REC_TICK_MS = 100
_LEVEL_BARS = 4

# Fenster-Stile: Klicks gehen durch die Anzeige hindurch, und sie nimmt dem
# Fenster, in das diktiert wird, nie den Fokus weg
_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_NOACTIVATE = 0x08000000
_SPI_GETCLIENTAREAANIMATION = 0x1042

# Diese Farbe wird per -transparentcolor ausgestanzt -> runde Ecken
_TRANSPARENT = "#000001"
_MARGIN = 16
_HEIGHT = 28
# Live-Vorschau: Umbruchbreite und wie viel vom Textende gezeigt wird
_PREVIEW_WIDTH = 420
_PREVIEW_CHARS = 180
# Semantischer Flash-Key -> (i18n-Text-Key, Farbe). Trennt Anzeige (uebersetzbar)
# von der Farb-Logik, die unabhaengig von der Sprache stabil bleibt.
_FLASH = {
    "clip": ("overlay.clip", "cyan"),        # Text in der Zwischenablage (Einfuegen ging nicht)
    "short": ("overlay.short", "amber"),     # Aufnahme zu kurz
    "empty": ("overlay.empty", "amber"),     # nichts erkannt
    "too_long": ("overlay.too_long", "amber"),  # Transkription im Timeout
    "cpu_fallback": ("overlay.cpu_fallback", "amber"),  # GPU abgestuerzt -> CPU
    "ready": ("overlay.ready", "green"),     # First-Run-Hinweis
    "err_mic": ("overlay.err_mic", "red"),
    "err_whisper": ("overlay.err_whisper", "red"),
}


def _animations_enabled() -> bool:
    """Windows-Einstellung Barrierefreiheit > Visuelle Effekte > Animationseffekte."""
    try:
        flag = wintypes.BOOL(True)
        if ctypes.windll.user32.SystemParametersInfoW(
                _SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(flag), 0):
            return bool(flag.value)
    except Exception:
        pass
    return True


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class RecordingOverlay:
    """Minimales Overlay — Canvas mit abgerundetem Hintergrund + Statustext."""

    def __init__(self, get_level=None):
        self._thread = None
        self._root = None
        self._canvas = None
        self._bg_id = None
        self._dot_id = None
        self._text_id = None
        self._bar_ids = []
        self._ready = threading.Event()
        self._anim_frame = 0
        self._anim_active = False
        self._flash_job = None
        self._anim_job = None
        self._rec_job = None
        self._rec_started = 0.0
        self._rec_shown_sec = -1
        self._get_level = get_level
        self._bg_spec = None
        self._border_color = BRAND["border"]
        self._scale = 1.0
        self._preview_id = None
        self._recording = False
        self._corner = None  # untere rechte Ecke (x, y) der letzten Platzierung
        self._animate = True  # Windows-Einstellung "Animationseffekte"

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
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        previous = user32.GetForegroundWindow()
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
        # 4 dezente Mini-Pegelbalken neben REC (nur waehrend Aufnahme sichtbar)
        self._bar_ids = [
            self._canvas.create_rectangle(0, 0, 0, 0, fill=BRAND["border"], outline="",
                                          state="hidden")
            for _ in range(_LEVEL_BARS)
        ]
        self._preview_id = self._canvas.create_text(
            self._px(16), h, text="", anchor="nw", width=self._px(_PREVIEW_WIDTH),
            font=("Segoe UI" if is_rtl() else FONT_BODY, 11), fill=BRAND["text"])
        self._layout("REC")

        self._root.withdraw()
        self._animate = _animations_enabled()
        # Tk aktiviert ein neues Fenster beim Erzeugen, und versteckt behielt
        # es den Fokus bis zum ersten Aus- und Einblenden — das erste Diktat
        # nach dem Start waere im Overlay statt im Zielfenster gelandet.
        # Fokus dem Fenster zurueckgeben, das ihn vorher hatte.
        try:
            self._root.update_idletasks()
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
            if previous and pid.value == os.getpid():
                user32.SetForegroundWindow(previous)
        except Exception:
            log.debug("Overlay: Fokus-Rueckgabe fehlgeschlagen", exc_info=True)
        self._ready.set()
        self._root.mainloop()

    def _px(self, logical: int) -> int:
        return int(logical * self._scale)

    def _round_rect(self, x1, y1, x2, y2, r, **kwargs):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
               x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self._canvas.create_polygon(pts, smooth=True, **kwargs)

    def _layout(self, text: str, follow_mouse: bool = True):
        """Passt Canvas-Breite an den Text an und zeichnet den Hintergrund neu.

        follow_mouse=False behaelt den Monitor der letzten Platzierung — die
        Live-Vorschau soll beim Diktieren nicht dem Mauszeiger nachspringen."""
        if follow_mouse or self._corner is None:
            self._corner = self._find_corner()
        h = self._px(_HEIGHT)
        # Positionen der Statuszeile an aktuelle Monitor-DPI anpassen
        self._canvas.coords(self._dot_id, self._px(16), h // 2)
        self._canvas.coords(self._text_id, self._px(26), h // 2)

        # Echte gerenderte Ausdehnung statt Font.measure() — measure weicht auf
        # High-DPI minimal vom tatsaechlich gezeichneten Text ab (Punkte ragten raus).
        bbox = self._canvas.bbox(self._dot_id, self._text_id)
        if bbox:
            text_right = bbox[2]
        else:
            f = tkfont.Font(family=FONT_MONO, size=10, weight="bold")
            text_right = self._px(26) + f.measure(text)

        show_bars = self._recording and self._animate and self._get_level is not None
        bars_w = self._px(_LEVEL_BARS * 5 + 8) if show_bars else 0
        w = text_right + bars_w + self._px(16)

        # Live-Vorschau unter der Statuszeile: Panel waechst dynamisch mit dem
        # Text (bis _PREVIEW_WIDTH) und nach oben von der unteren rechten Ecke
        preview_txt = self._canvas.itemcget(self._preview_id, "text")
        if preview_txt:
            rtl = is_rtl()
            max_pw = self._px(_PREVIEW_WIDTH)
            self._canvas.itemconfigure(
                self._preview_id,
                width=max_pw,
                anchor="ne" if rtl else "nw",
                justify="right" if rtl else "left",
                font=("Segoe UI" if rtl else FONT_BODY, 11),
            )
            self._canvas.coords(self._preview_id, self._px(16), h)
            pbox = self._canvas.bbox(self._preview_id)
            if pbox:
                actual_pw = min(max_pw, pbox[2] - pbox[0])
                w = max(w, actual_pw + self._px(32))
                h = pbox[3] + self._px(10)
            if rtl:
                self._canvas.coords(self._preview_id, w - self._px(16), self._px(_HEIGHT))

        self._place_level_bars(text_right + self._px(10), show_bars)
        self._canvas.configure(width=w, height=h)

        border_color = self._border_color
        spec = (w, h, border_color)
        if spec != self._bg_spec:
            # Hintergrund nur neu erzeugen, wenn sich Groesse oder Rahmenfarbe aendert
            if self._bg_id is not None:
                self._canvas.delete(self._bg_id)
            inset = max(1, round(self._scale * 0.8))
            self._bg_id = self._round_rect(
                inset, inset, w - inset, h - inset, self._px(13),
                fill=BRAND["card"], outline=border_color, width=max(1, round(self._scale)),
            )
            self._canvas.tag_lower(self._bg_id)
            self._bg_spec = spec

        # Groesse und Position in EINEM Aufruf — sonst springt das nach oben
        # wachsende Panel einen Frame lang
        self._root.geometry(f"{w}x{h}+{self._corner[0] - w}+{self._corner[1] - h}")

    def _place_level_bars(self, x0: int, visible: bool):
        """Positioniert die 4 Mini-Pegelbalken neben dem REC-Text."""
        if not self._bar_ids:
            return
        if not visible:
            for bid in self._bar_ids:
                self._canvas.itemconfigure(bid, state="hidden")
            return
        level = 0.0
        try:
            level = max(0.0, min(1.0, float(self._get_level())))
        except Exception:
            pass
        cy = self._px(_HEIGHT) // 2
        bw = max(2, self._px(2))
        gap = max(3, self._px(5))
        # Charakteristische Kurve: innere Balken reagieren etwas hoeher
        weights = (0.55, 1.0, 0.85, 0.45)
        for i, bid in enumerate(self._bar_ids):
            bar_val = level * weights[i % len(weights)]
            half_h = max(self._px(2), int(self._px(6) * bar_val) + self._px(1))
            bx = x0 + i * gap
            color = BRAND["red"] if level > 0.06 else BRAND["border"]
            self._canvas.coords(bid, bx, cy - half_h, bx + bw, cy + half_h)
            self._canvas.itemconfigure(bid, fill=color, state="normal")

    def _find_corner(self) -> tuple[int, int]:
        """Untere rechte Ecke auf dem Monitor, auf dem der Mauszeiger steht."""
        try:
            pt = wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            mon = ctypes.windll.user32.MonitorFromPoint(pt, 2)  # MONITOR_DEFAULTTONEAREST
            info = _MONITORINFO()
            info.cbSize = ctypes.sizeof(_MONITORINFO)
            if ctypes.windll.user32.GetMonitorInfoW(mon, ctypes.byref(info)):
                work = info.rcWork
                dpi_scale = monitor_dpi_scale(pt.x, pt.y)
                if dpi_scale >= 1.0:
                    self._scale = dpi_scale
                return work.right - self._px(_MARGIN), work.bottom - self._px(_MARGIN)
        except Exception:
            pass
        return (self._root.winfo_screenwidth() - self._px(_MARGIN),
                self._root.winfo_screenheight() - self._px(60))

    # --- Thread-sichere API (alles via root.after auf den Tk-Thread) ---

    def _dispatch(self, fn):
        root = self._root
        if root is None:
            return
        try:
            root.after(0, fn)
        except (tk.TclError, RuntimeError):
            pass  # Overlay wird gerade beendet

    def update_state(self, state):
        self._dispatch(lambda: self._apply(state))

    def flash(self, key: str, duration_ms: int = 5000, **fmt):
        """Zeigt einen Status (semantischer Key, z.B. 'clip', 'err_mic', 'ready')
        und blendet nach duration_ms wieder aus. fmt fuellt Platzhalter (hotkey)."""
        self._dispatch(lambda: self._show_flash(key, duration_ms, fmt))

    def preview(self, text: str):
        """Live-Vorschautext waehrend der Aufnahme. Kommt er nach dem Ende
        der Aufnahme an, wird er verworfen (Reihenfolge ueber root.after)."""
        self._dispatch(lambda: self._show_preview(text))

    def stop(self):
        self._anim_active = False
        self._recording = False
        root, self._root = self._root, None
        if root is not None:
            try:
                root.after(0, root.destroy)
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

    def _show(self):
        """Einblenden. Die Fenster-Stile vorher UND nachher setzen: vorher,
        damit schon das erste Einblenden den Fokus nicht nimmt; nachher,
        weil Tk die Stile beim Einblenden teils neu aufbaut."""
        self._apply_styles()
        self._root.deiconify()
        self._apply_styles()

    def _apply_styles(self):
        try:
            user32 = ctypes.windll.user32
            user32.GetParent.restype = wintypes.HWND
            get = user32.GetWindowLongPtrW
            put = user32.SetWindowLongPtrW
            get.restype = put.restype = ctypes.c_ssize_t
            get.argtypes = [wintypes.HWND, ctypes.c_int]
            put.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            hwnd = user32.GetParent(self._root.winfo_id()) or self._root.winfo_id()
            style = get(hwnd, _GWL_EXSTYLE)
            wanted = style | _WS_EX_TRANSPARENT | _WS_EX_NOACTIVATE
            if wanted != style:
                put(hwnd, _GWL_EXSTYLE, wanted)
        except Exception:
            log.debug("Overlay: Fenster-Stile nicht setzbar", exc_info=True)

    def _cancel_anim(self):
        if self._anim_job is not None:
            try:
                self._root.after_cancel(self._anim_job)
            except Exception:
                pass
            self._anim_job = None

    def _cancel_rec_tick(self):
        if self._rec_job is not None:
            try:
                self._root.after_cancel(self._rec_job)
            except Exception:
                pass
            self._rec_job = None

    def _set_preview(self, text: str):
        self._canvas.itemconfigure(self._preview_id, text=text)

    def _show_preview(self, text: str):
        if not self._root or not self._recording:
            return
        if len(text) > _PREVIEW_CHARS:
            # Nur das Ende zeigen, am Wortanfang abschneiden (CJK schuetzen)
            tail = text[-_PREVIEW_CHARS:]
            parts = tail.split(" ", 1)
            text = "… " + (parts[1] if len(parts) == 2 and len(parts[0]) <= 24 else tail)
        if text == self._canvas.itemcget(self._preview_id, "text"):
            return  # unveraendert: kein Neuzeichnen, kein Neupositionieren
        self._set_preview(text)
        self._layout(self._canvas.itemcget(self._text_id, "text"), follow_mouse=False)

    def _set_content(self, text: str, color: str, border: str | None = None,
                     follow_mouse: bool = True):
        self._border_color = border or BRAND["border"]
        self._canvas.itemconfigure(self._dot_id, fill=color)
        self._canvas.itemconfigure(self._text_id, text=text, fill=color)
        self._layout(text, follow_mouse=follow_mouse)

    def _apply(self, state):
        if not self._root: return
        self._cancel_flash()
        self._cancel_rec_tick()
        self._recording = state == AppState.RECORDING
        self._set_preview("")
        if state == AppState.RECORDING:
            self._anim_active = False
            self._cancel_anim()
            self._rec_started = time.monotonic()
            self._rec_shown_sec = 0
            self._set_content(t("overlay.rec"), BRAND["red"], border=BRAND["border"])
            self._show()
            self._rec_job = self._root.after(_REC_TICK_MS, self._rec_tick)
        elif state == AppState.TRANSCRIBING:
            # Feld auf den breitesten Animations-Frame dimensionieren, damit die
            # Punkte waehrend der Animation nicht aus dem Kasten ragen
            self._set_content(max(TRANSCRIBING_FRAMES, key=len), BRAND["cyan"],
                              border=BRAND["border_hover"])
            self._show()
            # Animationen in Windows abgeschaltet: die drei Punkte stehen still
            if self._animate and not self._anim_active:
                # Alte Kette abbrechen: nach Transkribieren -> Flash ->
                # Transkribieren binnen 300 ms liefen sonst zwei parallel
                # und die Punkte doppelt so schnell
                self._cancel_anim()
                self._anim_active = True
                self._anim_frame = 0
                self._animate_step()
        else:
            self._anim_active = False
            self._cancel_anim()
            self._root.withdraw()

    def _rec_tick(self):
        """Aktualisiert Aufnahme-Timer (ab 1 s) und Mini-Pegelbalken."""
        self._rec_job = None
        if not self._recording or not self._root:
            return
        sec = int(time.monotonic() - self._rec_started)
        if sec >= 1 and sec != self._rec_shown_sec:
            self._rec_shown_sec = sec
            mins, rem = divmod(sec, 60)
            label = f"{t('overlay.rec')}  {mins}:{rem:02d}"
            self._canvas.itemconfigure(self._text_id, text=label)
            self._layout(label, follow_mouse=False)
        elif self._animate and self._get_level is not None:
            bbox = self._canvas.bbox(self._dot_id, self._text_id)
            if bbox:
                self._place_level_bars(bbox[2] + self._px(10), True)
        self._rec_job = self._root.after(_REC_TICK_MS, self._rec_tick)

    def _animate_step(self):
        """Animiert die Dots waehrend TRANSCRIBING."""
        if not self._anim_active or not self._root:
            return
        frame = TRANSCRIBING_FRAMES[self._anim_frame % len(TRANSCRIBING_FRAMES)]
        self._canvas.itemconfigure(self._text_id, text=frame)
        self._anim_frame += 1
        self._anim_job = self._root.after(ANIMATION_INTERVAL_MS, self._animate_step)

    def _show_flash(self, key: str, duration_ms: int, fmt: dict):
        if not self._root: return
        self._anim_active = False
        self._recording = False
        self._cancel_anim()
        self._cancel_rec_tick()
        self._cancel_flash()
        self._set_preview("")
        text_key, color_name = _FLASH.get(key, (None, "red"))
        text = t(text_key, **fmt) if text_key else key
        color = BRAND.get(color_name, BRAND["red"])
        border = BRAND["red"] if color_name == "red" else BRAND["border"]
        self._set_content(text, color, border=border)
        self._show()
        self._flash_job = self._root.after(duration_ms, self._end_flash)

    def _end_flash(self):
        self._flash_job = None
        if self._root:
            self._root.withdraw()
