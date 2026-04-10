"""VoZii Recording-Overlay — schlank, modern, haZii-Design."""

import threading
import customtkinter as ctk
from src.theme import BRAND, FONT_MONO
from src.state import AppState


class RecordingOverlay:

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
        self._root = ctk.CTk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.9)
        self._root.configure(fg_color="black")

        w, h = 110, 28
        x = self._root.winfo_screenwidth() - w - 16
        y = self._root.winfo_screenheight() - h - 60
        self._root.geometry(f"{w}x{h}+{x}+{y}")

        frame = ctk.CTkFrame(self._root, fg_color=BRAND["card"], corner_radius=14,
                             border_width=1, border_color=BRAND["border"])
        frame.pack(fill="both", expand=True)

        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(expand=True)

        self._bar = ctk.CTkLabel(row, text="●", font=(FONT_MONO, 10),
                                  text_color=BRAND["red"], width=14)
        self._bar.pack(side="left", padx=(8, 2))

        self._label = ctk.CTkLabel(row, text="REC", font=(FONT_MONO, 11, "bold"),
                                    text_color=BRAND["red"])
        self._label.pack(side="left", padx=(0, 8))

        self._root.withdraw()
        self._ready.set()
        self._root.mainloop()

    def update_state(self, state):
        if not self._root: return
        self._root.after(0, lambda: self._apply(state))

    def _apply(self, state):
        if not self._root: return
        if state == AppState.RECORDING:
            self._bar.configure(text_color=BRAND["red"])
            self._label.configure(text="REC", text_color=BRAND["red"])
            self._root.deiconify()
        elif state == AppState.TRANSCRIBING:
            self._bar.configure(text_color=BRAND["cyan"])
            self._label.configure(text="· · ·", text_color=BRAND["cyan"])
            self._root.deiconify()
        else:
            self._root.withdraw()

    def stop(self):
        if self._root:
            try: self._root.after(0, self._root.destroy)
            except: pass
