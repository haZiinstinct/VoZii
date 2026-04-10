"""VoZii Settings — Clean, minimal, borderless, haZii Design."""

import logging
import os
import threading

import customtkinter as ctk
from pynput import keyboard, mouse

from src import __version__
from src.theme import BRAND, FONT_BODY, FONT_MONO
from src.hotkey import key_to_name, mouse_button_to_name
from src.downloader import (
    is_binary_installed, is_model_installed,
    download_and_extract_binary, download_model,
)

log = logging.getLogger(__name__)

ctk.set_appearance_mode("dark")

MODEL_LABELS = {
    "tiny": "Tiny  (75 MB, schnell)",
    "small": "Small  (465 MB, ausgewogen)",
    "medium": "Medium  (1.5 GB, genau)",
}


class SettingsWindow:

    def __init__(self, config, gpu_info, backend_name, available_devices):
        self.config = dict(config)
        self.gpu_type, self.gpu_name = gpu_info
        self.backend_name = backend_name
        self.available_devices = available_devices
        self._recording_hotkey = False
        self._pressed_keys = set()
        self._current_combo = []
        self._kb_listener = None
        self._mouse_listener = None
        self._result = None
        self._drag_x = self._drag_y = 0
        self._downloading = False
        self._cancel_download = threading.Event()

    def run(self):
        self.root = ctk.CTk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(fg_color=BRAND["bg"])

        w, h = 440, 580
        sx = (self.root.winfo_screenwidth() - w) // 2
        sy = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{sx}+{sy}")

        # Border
        border = ctk.CTkFrame(self.root, fg_color=BRAND["card"], corner_radius=16,
                              border_width=1, border_color=BRAND["border"])
        border.pack(fill="both", expand=True, padx=1, pady=1)
        inner = ctk.CTkFrame(border, fg_color=BRAND["bg"], corner_radius=14)
        inner.pack(fill="both", expand=True, padx=2, pady=2)

        # Titlebar
        tb = ctk.CTkFrame(inner, fg_color="transparent", height=48)
        tb.pack(fill="x", padx=20, pady=(16, 0))
        tb.bind("<Button-1>", self._start_drag)
        tb.bind("<B1-Motion>", self._do_drag)
        ctk.CTkLabel(tb, text="VoZii", font=(FONT_MONO, 22, "bold"),
                     text_color=BRAND["cyan"]).pack(side="left")
        ctk.CTkLabel(tb, text=f"v{__version__}", font=(FONT_MONO, 10),
                     text_color=BRAND["text_dim"]).pack(side="left", padx=(6, 0), pady=(6, 0))
        ctk.CTkButton(tb, text="×", width=28, height=28, font=(FONT_MONO, 16),
                      fg_color="transparent", text_color=BRAND["text_dim"],
                      hover_color=BRAND["red"], corner_radius=14,
                      command=self._cancel).pack(side="right")

        ctk.CTkLabel(inner, text=f"{self.backend_name}  ·  {self.gpu_name or 'CPU'}",
                     font=(FONT_BODY, 12), text_color=BRAND["text_dim"]
                     ).pack(anchor="w", padx=24, pady=(2, 16))

        c = ctk.CTkFrame(inner, fg_color="transparent")
        c.pack(fill="both", expand=True, padx=24)

        # HOTKEY
        self._heading(c, "Hotkey")
        hk = ctk.CTkFrame(c, fg_color="transparent")
        hk.pack(fill="x", pady=(0, 14))
        self.hotkey_label = ctk.CTkLabel(hk, text=self.config["hotkey"].upper().replace("+", " + "),
                                         font=(FONT_MONO, 18, "bold"), text_color=BRAND["text_bright"])
        self.hotkey_label.pack(side="left")
        ctk.CTkButton(hk, text="Aendern", width=80, height=30, font=(FONT_BODY, 12),
                      fg_color=BRAND["card"], text_color=BRAND["text"],
                      hover_color=BRAND["card_hover"], corner_radius=8,
                      border_width=1, border_color=BRAND["border"],
                      command=self._start_recording).pack(side="right")

        # MODELL + DOWNLOAD
        self._heading(c, "Modell")
        mr = ctk.CTkFrame(c, fg_color="transparent")
        mr.pack(fill="x", pady=(0, 4))
        opts = list(MODEL_LABELS.values())
        key_map = {"tiny": opts[0], "small": opts[1], "medium": opts[2]}
        self.model_var = ctk.StringVar(value=key_map.get(self.config["model_size"], opts[1]))
        ctk.CTkOptionMenu(mr, values=opts, variable=self.model_var, font=(FONT_BODY, 13),
                          width=260, fg_color=BRAND["card"], button_color=BRAND["card_hover"],
                          button_hover_color=BRAND["cyan_dim"], dropdown_fg_color=BRAND["card"],
                          dropdown_hover_color=BRAND["card_hover"], dropdown_text_color=BRAND["text"],
                          text_color=BRAND["text"], corner_radius=8,
                          command=self._on_model_change).pack(side="left")
        self.dl_btn = ctk.CTkButton(mr, text="Download", width=100, height=32,
                                     font=(FONT_BODY, 12, "bold"), fg_color=BRAND["cyan"],
                                     text_color=BRAND["bg"], hover_color=BRAND["cyan_dim"],
                                     corner_radius=8, command=self._download_current_model)
        self.dl_btn.pack(side="right")

        self.progress = ctk.CTkProgressBar(c, progress_color=BRAND["cyan"],
                                            fg_color=BRAND["card"], height=4, corner_radius=2)
        self.progress.pack(fill="x", pady=(4, 2))
        self.progress.set(0)
        self.progress_text = ctk.CTkLabel(c, text="", font=(FONT_BODY, 11),
                                           text_color=BRAND["text_dim"], height=16)
        self.progress_text.pack(anchor="w", pady=(0, 10))
        self._update_dl_button()

        # SPRACHE
        self._heading(c, "Sprache")
        lang_map = {"de": "Deutsch", "en": "English", "auto": "Auto"}
        self.lang_var = ctk.StringVar(value=lang_map.get(self.config["language"], "Deutsch"))
        ctk.CTkSegmentedButton(c, values=["Deutsch", "English", "Auto"], variable=self.lang_var,
                               font=(FONT_BODY, 13), selected_color=BRAND["cyan"],
                               selected_hover_color=BRAND["cyan_dim"], unselected_color=BRAND["card"],
                               unselected_hover_color=BRAND["card_hover"],
                               text_color=BRAND["text_bright"], fg_color=BRAND["card"],
                               corner_radius=8).pack(fill="x", pady=(0, 14))

        # MIKROFON
        self._heading(c, "Mikrofon")
        devs = ["Standard"] + [d["name"] for d in self.available_devices]
        cur_dev = "Standard"
        if self.config.get("audio_device"):
            for d in self.available_devices:
                if d["name"] == self.config["audio_device"]:
                    cur_dev = d["name"]
                    break
        self.mic_var = ctk.StringVar(value=cur_dev)
        ctk.CTkOptionMenu(c, values=devs, variable=self.mic_var, font=(FONT_BODY, 13),
                          fg_color=BRAND["card"], button_color=BRAND["card_hover"],
                          button_hover_color=BRAND["cyan_dim"], dropdown_fg_color=BRAND["card"],
                          dropdown_hover_color=BRAND["card_hover"], dropdown_text_color=BRAND["text"],
                          text_color=BRAND["text"], corner_radius=8).pack(fill="x", pady=(0, 14))

        # OPTIONS
        self.overlay_var = ctk.BooleanVar(value=self.config.get("show_overlay", True))
        ctk.CTkSwitch(c, text="Recording-Indikator", variable=self.overlay_var,
                      font=(FONT_BODY, 13), text_color=BRAND["text"],
                      progress_color=BRAND["cyan"], button_color=BRAND["text_dim"],
                      button_hover_color=BRAND["text"]).pack(anchor="w", pady=(0, 6))

        self.autostart_var = ctk.BooleanVar(value=self.config.get("auto_start", False))
        ctk.CTkSwitch(c, text="Mit Windows starten", variable=self.autostart_var,
                      font=(FONT_BODY, 13), text_color=BRAND["text"],
                      progress_color=BRAND["cyan"], button_color=BRAND["text_dim"],
                      button_hover_color=BRAND["text"]).pack(anchor="w", pady=(0, 16))

        # START
        ctk.CTkButton(c, text="Starten", height=44, font=(FONT_BODY, 16, "bold"),
                      fg_color=BRAND["cyan"], text_color=BRAND["bg"],
                      hover_color=BRAND["cyan_dim"], corner_radius=10,
                      command=self._save).pack(fill="x", pady=(4, 0))

        self.root.mainloop()
        return self._result

    def _heading(self, parent, text):
        ctk.CTkLabel(parent, text=text.upper(), font=(FONT_BODY, 12, "bold"),
                     text_color=BRAND["text_dim"]).pack(anchor="w", pady=(0, 4))

    def _start_drag(self, e):
        self._drag_x, self._drag_y = e.x, e.y

    def _do_drag(self, e):
        self.root.geometry(f"+{self.root.winfo_x() + e.x - self._drag_x}+{self.root.winfo_y() + e.y - self._drag_y}")

    # Model
    def _get_model_size(self):
        v = self.model_var.get().lower()
        return "tiny" if "tiny" in v else "medium" if "medium" in v else "small"

    def _on_model_change(self, _):
        self._update_dl_button()

    def _update_dl_button(self):
        ok = is_binary_installed() and is_model_installed(self._get_model_size())
        if ok:
            self.dl_btn.configure(text="Bereit ✓", state="disabled",
                                  fg_color=BRAND["card"], text_color=BRAND["green"])
        else:
            self.dl_btn.configure(text="Download", state="normal",
                                  fg_color=BRAND["cyan"], text_color=BRAND["bg"])

    def _download_current_model(self):
        if self._downloading:
            self._cancel_download.set()
            self._downloading = False
            return

        size = self._get_model_size()
        self._downloading = True
        self._cancel_download.clear()
        self.dl_btn.configure(text="Abbrechen", fg_color=BRAND["red"], hover_color="#dc2626")

        def run():
            try:
                if not is_binary_installed():
                    self._msg("Lade whisper.cpp...")
                    download_and_extract_binary(self.gpu_type, self._checked_progress)
                if self._cancel_download.is_set(): raise InterruptedError
                if not is_model_installed(size):
                    self._msg(f"Lade Modell '{size}'...")
                    download_model(size, self._checked_progress)
                if self._cancel_download.is_set(): raise InterruptedError
                self.root.after(0, self._dl_done)
            except InterruptedError:
                self.root.after(0, lambda: self._dl_fail("Abgebrochen"))
            except Exception as e:
                self.root.after(0, lambda: self._dl_fail(str(e)))
            finally:
                self._downloading = False

        threading.Thread(target=run, daemon=True).start()

    def _checked_progress(self, dl, total):
        if self._cancel_download.is_set(): raise InterruptedError
        f = dl / total if total else 0
        self.root.after(0, lambda: self.progress.set(f))
        self.root.after(0, lambda: self.progress_text.configure(
            text=f"{dl // 1048576} / {total // 1048576} MB"))

    def _msg(self, t):
        self.root.after(0, lambda: self.progress_text.configure(text=t, text_color=BRAND["text_dim"]))

    def _dl_done(self):
        self.progress.set(1.0)
        self.progress_text.configure(text="Fertig!", text_color=BRAND["green"])
        self._update_dl_button()

    def _dl_fail(self, msg):
        self.progress.set(0)
        self.progress_text.configure(text=msg, text_color=BRAND["red"])
        self._update_dl_button()

    # Hotkey Recording
    def _start_recording(self):
        self._recording_hotkey = True
        self._pressed_keys = set()
        self._current_combo = []
        self.hotkey_label.configure(text="Druecke Tasten...", text_color=BRAND["amber"])
        self._kb_listener = keyboard.Listener(on_press=self._on_kp, on_release=self._on_kr)
        self._kb_listener.start()
        self._mouse_listener = mouse.Listener(on_click=self._on_mc)
        self._mouse_listener.start()

    def _on_kp(self, key):
        if not self._recording_hotkey: return
        n = key_to_name(key)
        if n not in self._pressed_keys:
            self._pressed_keys.add(n)
            self._current_combo.append(n)
            self._show_combo()

    def _on_mc(self, x, y, btn, pressed):
        if not self._recording_hotkey: return
        if btn in (mouse.Button.left, mouse.Button.right): return
        n = mouse_button_to_name(btn)
        if pressed and n not in self._pressed_keys:
            self._pressed_keys.add(n)
            self._current_combo.append(n)
            self._show_combo()
        elif not pressed and self._current_combo:
            self._finalize()

    def _on_kr(self, key):
        if self._recording_hotkey and self._current_combo:
            self._finalize()

    def _show_combo(self):
        d = " + ".join(k.upper() for k in self._current_combo)
        self.root.after(0, lambda: self.hotkey_label.configure(text=d))

    def _finalize(self):
        if not self._recording_hotkey: return
        self._recording_hotkey = False
        self._stop_listeners()
        self.config["hotkey"] = "+".join(self._current_combo)
        d = " + ".join(k.upper() for k in self._current_combo)
        self.root.after(0, lambda: self.hotkey_label.configure(text=d, text_color=BRAND["text_bright"]))

    def _stop_listeners(self):
        for l in (self._kb_listener, self._mouse_listener):
            if l:
                try:
                    l.stop()
                except Exception as e:
                    log.warning("Listener stop failed: %s", e)
        self._kb_listener = self._mouse_listener = None

    # Save / Cancel
    def _save(self):
        lang_map = {"Deutsch": "de", "English": "en", "Auto": "auto"}
        self.config.update({
            "language": lang_map.get(self.lang_var.get(), "de"),
            "model_size": self._get_model_size(),
            "show_overlay": self.overlay_var.get(),
            "auto_start": self.autostart_var.get(),
            "audio_device": None if self.mic_var.get() == "Standard" else self.mic_var.get(),
        })
        self._result = self.config
        self._stop_listeners()
        self.root.destroy()

    def _cancel(self):
        self._result = None
        self._stop_listeners()
        self.root.destroy()
