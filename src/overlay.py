"""VoZii Floating Recording-Indikator im haZii-Design."""

import threading

import customtkinter as ctk

from src.theme import BRAND, FONT_BODY, FONT_MONO
from src.state import AppState


class RecordingOverlay:
    """Kleines borderlose Overlay unten rechts: zeigt REC / Transkribiert / versteckt."""

    def __init__(self):
        self._thread = None
        self._root = None
        self._label = None
        self._dot = None
        self._ready = threading.Event()

    def start(self):
        """Startet den Overlay-Thread."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3)

    def _run(self):
        self._root = ctk.CTk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.92)
        self._root.configure(fg_color=BRAND["card"])

        w, h = 150, 44
        screen_w = self._root.winfo_screenwidth()
        screen_h = self._root.winfo_screenheight()
        x = screen_w - w - 20
        y = screen_h - h - 80
        self._root.geometry(f"{w}x{h}+{x}+{y}")

        frame = ctk.CTkFrame(
            self._root, fg_color=BRAND["card"],
            border_width=1, border_color=BRAND["border"],
            corner_radius=12,
        )
        frame.pack(fill="both", expand=True)

        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=12)

        self._dot = ctk.CTkLabel(
            inner, text="●", font=(FONT_BODY, 18),
            text_color=BRAND["red"], width=20,
        )
        self._dot.pack(side="left")

        self._label = ctk.CTkLabel(
            inner, text="REC",
            font=(FONT_MONO, 14, "bold"),
            text_color=BRAND["red"],
        )
        self._label.pack(side="left", padx=(4, 0))

        # Start hidden
        self._root.withdraw()
        self._ready.set()
        self._root.mainloop()

    def update_state(self, state: AppState):
        """Thread-safe State-Update."""
        if not self._root:
            return
        self._root.after(0, lambda: self._apply_state(state))

    def _apply_state(self, state: AppState):
        if not self._root:
            return

        if state == AppState.RECORDING:
            self._dot.configure(text_color=BRAND["red"])
            self._label.configure(text="REC", text_color=BRAND["red"])
            self._root.deiconify()
        elif state == AppState.TRANSCRIBING:
            self._dot.configure(text_color=BRAND["cyan"])
            self._label.configure(text="...", text_color=BRAND["cyan"])
            self._root.deiconify()
        else:
            self._root.withdraw()

    def stop(self):
        if self._root:
            try:
                self._root.after(0, self._root.destroy)
            except Exception:
                pass
