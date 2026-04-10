"""VoZii Recording-Overlay — schlank, unsichtbar in Taskbar."""

import logging
import threading
import tkinter as tk
from src.theme import BRAND, FONT_MONO
from src.state import AppState

log = logging.getLogger(__name__)


class RecordingOverlay:
    """Minimales Overlay — nutzt raw tkinter um kein zweites Tray-Icon zu erzeugen."""

    def __init__(self):
        self._thread = None
        self._root = None
        self._bar = None
        self._label = None
        self._ready = threading.Event()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3)

    def _run(self):
        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.9)
        self._root.attributes("-toolwindow", True)
        self._root.configure(bg=BRAND["card"])

        w, h = 100, 26
        x = self._root.winfo_screenwidth() - w - 16
        y = self._root.winfo_screenheight() - h - 60
        self._root.geometry(f"{w}x{h}+{x}+{y}")

        frame = tk.Frame(self._root, bg=BRAND["card"])
        frame.pack(fill="both", expand=True)

        self._bar = tk.Label(frame, text="●", font=(FONT_MONO, 9),
                             fg=BRAND["red"], bg=BRAND["card"])
        self._bar.pack(side="left", padx=(10, 2))

        self._label = tk.Label(frame, text="REC", font=(FONT_MONO, 10, "bold"),
                               fg=BRAND["red"], bg=BRAND["card"])
        self._label.pack(side="left", padx=(0, 10))

        self._root.withdraw()
        self._ready.set()
        self._root.mainloop()

    def update_state(self, state):
        if not self._root: return
        self._root.after(0, lambda: self._apply(state))

    def _apply(self, state):
        if not self._root: return
        if state == AppState.RECORDING:
            self._bar.configure(fg=BRAND["red"])
            self._label.configure(text="REC", fg=BRAND["red"])
            self._root.deiconify()
        elif state == AppState.TRANSCRIBING:
            self._bar.configure(fg=BRAND["cyan"])
            self._label.configure(text="· · ·", fg=BRAND["cyan"])
            self._root.deiconify()
        else:
            self._root.withdraw()

    def flash_error(self, msg: str = "ERR"):
        """Zeigt das Overlay 3 Sekunden rot mit Fehler-Text."""
        if not self._root: return
        self._root.after(0, lambda: self._show_error(msg))

    def _show_error(self, msg: str):
        if not self._root: return
        self._bar.configure(fg=BRAND["red"])
        self._label.configure(text="ERR", fg=BRAND["red"])
        self._root.deiconify()
        self._root.after(3000, self._root.withdraw)

    def stop(self):
        if self._root:
            try:
                self._root.after(0, self._root.destroy)
            except Exception as e:
                log.warning("Overlay destroy failed: %s", e)
