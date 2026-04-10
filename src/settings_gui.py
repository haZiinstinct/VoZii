"""VoZii Settings — Clean, minimal, borderless, haZii Design."""

import os
import threading

import customtkinter as ctk
from pynput import keyboard, mouse

from src.theme import BRAND, FONT_BODY, FONT_MONO, APP_NAME
from src.hotkey import key_to_name, mouse_button_to_name
from src.downloader import (
    is_binary_installed, is_model_installed,
    download_and_extract_binary, download_model,
)

ctk.set_appearance_mode("dark")

MODEL_LABELS = {
    "tiny": "Tiny  (75 MB, schnell)",
    "small": "Small  (465 MB, ausgewogen)",
    "medium": "Medium  (1.5 GB, genau)",
}


class SettingsWindow:

    def __init__(self, config: dict, gpu_info: tuple[str, str],
                 backend_name: str, available_devices: list[dict]):
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
        self._drag_x = 0
        self._drag_y = 0
        self._downloading = False
        self._cancel_download = threading.Event()

    def run(self) -> dict | None:
        self.root = ctk.CTk()
        self.root.overrideredirect(True)  # Borderless
        self.root.attributes("-topmost", True)
        self.root.configure(fg_color=BRAND["bg"])

        # Center on screen
        w, h = 440, 580
        sx = (self.root.winfo_screenwidth() - w) // 2
        sy = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{sx}+{sy}")

        # Outer border frame
        border = ctk.CTkFrame(self.root, fg_color=BRAND["card"], corner_radius=16,
                              border_width=1, border_color=BRAND["border"])
        border.pack(fill="both", expand=True, padx=1, pady=1)

        inner = ctk.CTkFrame(border, fg_color=BRAND["bg"], corner_radius=14)
        inner.pack(fill="both", expand=True, padx=2, pady=2)

        # === TITLE BAR (draggable) ===
        titlebar = ctk.CTkFrame(inner, fg_color="transparent", height=48)
        titlebar.pack(fill="x", padx=20, pady=(16, 0))
        titlebar.bind("<Button-1>", self._start_drag)
        titlebar.bind("<B1-Motion>", self._do_drag)

        ctk.CTkLabel(
            titlebar, text="VoZii",
            font=(FONT_MONO, 22, "bold"), text_color=BRAND["cyan"],
        ).pack(side="left")

        # Close button
        close_btn = ctk.CTkButton(
            titlebar, text="✕", width=32, height=32,
            font=(FONT_BODY, 14), fg_color="transparent",
            text_color=BRAND["text_dim"], hover_color=BRAND["card_hover"],
            corner_radius=8, command=self._cancel,
        )
        close_btn.pack(side="right")

        # Subtitle
        ctk.CTkLabel(
            inner, text=f"{self.backend_name}  ·  {self.gpu_name or 'CPU'}",
            font=(FONT_BODY, 12), text_color=BRAND["text_dim"],
        ).pack(anchor="w", padx=24, pady=(2, 16))

        # === CONTENT ===
        content = ctk.CTkFrame(inner, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=24)

        # --- HOTKEY ---
        self._label(content, "HOTKEY")

        hk_row = ctk.CTkFrame(content, fg_color="transparent")
        hk_row.pack(fill="x", pady=(0, 14))

        self.hotkey_label = ctk.CTkLabel(
            hk_row,
            text=self.config["hotkey"].upper().replace("+", " + "),
            font=(FONT_MONO, 18, "bold"), text_color=BRAND["text_bright"],
        )
        self.hotkey_label.pack(side="left")

        ctk.CTkButton(
            hk_row, text="Aendern", width=80, height=30,
            font=(FONT_BODY, 12),
            fg_color=BRAND["card"], text_color=BRAND["text"],
            hover_color=BRAND["card_hover"], corner_radius=8,
            border_width=1, border_color=BRAND["border"],
            command=self._start_recording,
        ).pack(side="right")

        # --- MODELL + DOWNLOAD ---
        self._label(content, "MODELL")

        model_row = ctk.CTkFrame(content, fg_color="transparent")
        model_row.pack(fill="x", pady=(0, 4))

        model_options = list(MODEL_LABELS.values())
        model_key_map = {"tiny": model_options[0], "small": model_options[1], "medium": model_options[2]}
        current = model_key_map.get(self.config["model_size"], model_options[1])

        self.model_var = ctk.StringVar(value=current)
        ctk.CTkOptionMenu(
            model_row, values=model_options, variable=self.model_var,
            font=(FONT_BODY, 13), width=260,
            fg_color=BRAND["card"], button_color=BRAND["card_hover"],
            button_hover_color=BRAND["cyan_dim"],
            dropdown_fg_color=BRAND["card"], dropdown_hover_color=BRAND["card_hover"],
            dropdown_text_color=BRAND["text"], text_color=BRAND["text"],
            corner_radius=8, command=self._on_model_change,
        ).pack(side="left")

        self.dl_btn = ctk.CTkButton(
            model_row, text="Download", width=100, height=32,
            font=(FONT_BODY, 12, "bold"),
            fg_color=BRAND["cyan"], text_color=BRAND["bg"],
            hover_color=BRAND["cyan_dim"], corner_radius=8,
            command=self._download_current_model,
        )
        self.dl_btn.pack(side="right")

        # Progress
        self.progress = ctk.CTkProgressBar(
            content, progress_color=BRAND["cyan"],
            fg_color=BRAND["card"], height=4, corner_radius=2,
        )
        self.progress.pack(fill="x", pady=(4, 2))
        self.progress.set(0)

        self.progress_text = ctk.CTkLabel(
            content, text="", font=(FONT_BODY, 11), text_color=BRAND["text_dim"], height=16,
        )
        self.progress_text.pack(anchor="w", pady=(0, 10))

        self._update_dl_button()

        # --- SPRACHE ---
        self._label(content, "SPRACHE")

        lang_map = {"de": "Deutsch", "en": "English", "auto": "Auto"}
        current_lang = lang_map.get(self.config["language"], "Deutsch")

        self.lang_var = ctk.StringVar(value=current_lang)
        ctk.CTkSegmentedButton(
            content, values=["Deutsch", "English", "Auto"],
            variable=self.lang_var,
            font=(FONT_BODY, 13),
            selected_color=BRAND["cyan"], selected_hover_color=BRAND["cyan_dim"],
            unselected_color=BRAND["card"], unselected_hover_color=BRAND["card_hover"],
            text_color=BRAND["text_bright"],
            fg_color=BRAND["card"],
            corner_radius=8,
        ).pack(fill="x", pady=(0, 14))

        # --- MIKROFON ---
        self._label(content, "MIKROFON")

        device_names = ["Standard"] + [d["name"] for d in self.available_devices]
        current_device = "Standard"
        if self.config.get("audio_device"):
            for d in self.available_devices:
                if d["name"] == self.config["audio_device"]:
                    current_device = d["name"]
                    break

        self.mic_var = ctk.StringVar(value=current_device)
        ctk.CTkOptionMenu(
            content, values=device_names, variable=self.mic_var,
            font=(FONT_BODY, 13),
            fg_color=BRAND["card"], button_color=BRAND["card_hover"],
            button_hover_color=BRAND["cyan_dim"],
            dropdown_fg_color=BRAND["card"], dropdown_hover_color=BRAND["card_hover"],
            dropdown_text_color=BRAND["text"], text_color=BRAND["text"],
            corner_radius=8,
        ).pack(fill="x", pady=(0, 14))

        # --- OPTIONS ---
        self.overlay_var = ctk.BooleanVar(value=self.config.get("show_overlay", True))
        ctk.CTkSwitch(
            content, text="Recording-Indikator", variable=self.overlay_var,
            font=(FONT_BODY, 13), text_color=BRAND["text"],
            progress_color=BRAND["cyan"], button_color=BRAND["text_dim"],
            button_hover_color=BRAND["text"],
        ).pack(anchor="w", pady=(0, 6))

        self.autostart_var = ctk.BooleanVar(value=self.config.get("auto_start", False))
        ctk.CTkSwitch(
            content, text="Mit Windows starten", variable=self.autostart_var,
            font=(FONT_BODY, 13), text_color=BRAND["text"],
            progress_color=BRAND["cyan"], button_color=BRAND["text_dim"],
            button_hover_color=BRAND["text"],
        ).pack(anchor="w", pady=(0, 16))

        # === START BUTTON ===
        ctk.CTkButton(
            content, text="Starten", height=44,
            font=(FONT_BODY, 16, "bold"),
            fg_color=BRAND["cyan"], text_color=BRAND["bg"],
            hover_color=BRAND["cyan_dim"], corner_radius=10,
            command=self._save,
        ).pack(fill="x", pady=(4, 0))

        self.root.mainloop()
        return self._result

    # --- Helpers ---

    def _label(self, parent, text):
        ctk.CTkLabel(
            parent, text=text,
            font=(FONT_MONO, 10), text_color=BRAND["text_dim"],
        ).pack(anchor="w", pady=(0, 4))

    def _start_drag(self, e):
        self._drag_x = e.x
        self._drag_y = e.y

    def _do_drag(self, e):
        x = self.root.winfo_x() + e.x - self._drag_x
        y = self.root.winfo_y() + e.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    # --- Model ---

    def _get_model_size(self) -> str:
        val = self.model_var.get().lower()
        if "tiny" in val: return "tiny"
        if "medium" in val: return "medium"
        return "small"

    def _on_model_change(self, _):
        self._update_dl_button()

    def _update_dl_button(self):
        size = self._get_model_size()
        binary_ok = is_binary_installed()
        model_ok = is_model_installed(size)

        if binary_ok and model_ok:
            self.dl_btn.configure(text="Bereit ✓", state="disabled",
                                  fg_color=BRAND["card"], text_color=BRAND["green"])
        elif not binary_ok:
            self.dl_btn.configure(text="Setup", state="normal",
                                  fg_color=BRAND["cyan"], text_color=BRAND["bg"])
        else:
            self.dl_btn.configure(text="Download", state="normal",
                                  fg_color=BRAND["cyan"], text_color=BRAND["bg"])

    def _download_current_model(self):
        # Toggle: klick startet, nochmal klick bricht ab
        if self._downloading:
            self._cancel_download.set()
            self.dl_btn.configure(text="Abgebrochen", state="disabled")
            self._downloading = False
            return

        size = self._get_model_size()
        self._downloading = True
        self._cancel_download.clear()
        self.dl_btn.configure(text="Abbrechen", fg_color=BRAND["red"],
                              hover_color="#dc2626")

        def run():
            try:
                if not is_binary_installed():
                    self._set_progress_text("Lade whisper.cpp...")
                    download_and_extract_binary(self.gpu_type,
                        progress_callback=self._check_cancel_progress)

                if self._cancel_download.is_set():
                    raise InterruptedError("Abgebrochen")

                if not is_model_installed(size):
                    self._set_progress_text(f"Lade Modell '{size}'...")
                    download_model(size, progress_callback=self._check_cancel_progress)

                if self._cancel_download.is_set():
                    raise InterruptedError("Abgebrochen")

                self.root.after(0, lambda: self._download_done())
            except InterruptedError:
                self.root.after(0, lambda: self._download_error("Download abgebrochen"))
            except Exception as e:
                self.root.after(0, lambda: self._download_error(str(e)))
            finally:
                self._downloading = False

        threading.Thread(target=run, daemon=True).start()

    def _check_cancel_progress(self, downloaded, total):
        if self._cancel_download.is_set():
            raise InterruptedError("Abgebrochen")
        self._update_progress(downloaded, total)

    def _update_progress(self, downloaded, total):
        frac = downloaded / total if total > 0 else 0
        mb = downloaded / (1024 * 1024)
        mb_t = total / (1024 * 1024)
        self.root.after(0, lambda: self.progress.set(frac))
        self.root.after(0, lambda: self.progress_text.configure(
            text=f"{mb:.0f} / {mb_t:.0f} MB", text_color=BRAND["text_dim"]
        ))

    def _set_progress_text(self, text):
        self.root.after(0, lambda: self.progress_text.configure(text=text))

    def _download_done(self):
        self._downloading = False
        self.progress.set(1.0)
        self.progress_text.configure(text="Fertig!", text_color=BRAND["green"])
        self._update_dl_button()

    def _download_error(self, msg):
        self._downloading = False
        self.progress.set(0)
        self.progress_text.configure(text=msg, text_color=BRAND["red"])
        self._update_dl_button()

    # --- Hotkey Recording ---

    def _start_recording(self):
        self._recording_hotkey = True
        self._pressed_keys = set()
        self._current_combo = []
        self.hotkey_label.configure(text="Druecke Tasten...", text_color=BRAND["amber"])

        self._kb_listener = keyboard.Listener(
            on_press=self._on_key_press, on_release=self._on_key_release)
        self._kb_listener.start()
        self._mouse_listener = mouse.Listener(on_click=self._on_mouse_click)
        self._mouse_listener.start()

    def _on_key_press(self, key):
        if not self._recording_hotkey: return
        name = key_to_name(key)
        if name not in self._pressed_keys:
            self._pressed_keys.add(name)
            self._current_combo.append(name)
            self._show_combo()

    def _on_mouse_click(self, x, y, button, pressed):
        if not self._recording_hotkey: return
        if button in (mouse.Button.left, mouse.Button.right): return
        name = mouse_button_to_name(button)
        if pressed:
            if name not in self._pressed_keys:
                self._pressed_keys.add(name)
                self._current_combo.append(name)
                self._show_combo()
        else:
            # Mouse button released → finalize (Mouse-only hotkey OK)
            if self._current_combo:
                self._finalize_hotkey()

    def _on_key_release(self, key):
        if not self._recording_hotkey or not self._current_combo: return
        self._finalize_hotkey()

    def _show_combo(self):
        display = " + ".join(k.upper() for k in self._current_combo)
        self.root.after(0, lambda: self.hotkey_label.configure(text=display))

    def _finalize_hotkey(self):
        if not self._recording_hotkey: return
        self._recording_hotkey = False
        self._stop_listeners()
        self.config["hotkey"] = "+".join(self._current_combo)
        display = " + ".join(k.upper() for k in self._current_combo)
        self.root.after(0, lambda: self.hotkey_label.configure(
            text=display, text_color=BRAND["text_bright"]))

    def _stop_listeners(self):
        if self._kb_listener:
            self._kb_listener.stop()
            self._kb_listener = None
        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener = None

    # --- Save / Cancel ---

    def _save(self):
        lang_map = {"Deutsch": "de", "English": "en", "Auto": "auto"}
        self.config["language"] = lang_map.get(self.lang_var.get(), "de")
        self.config["model_size"] = self._get_model_size()
        self.config["show_overlay"] = self.overlay_var.get()
        self.config["auto_start"] = self.autostart_var.get()
        mic = self.mic_var.get()
        self.config["audio_device"] = None if mic == "Standard" else mic
        self._result = self.config
        self._stop_listeners()
        self.root.destroy()

    def _cancel(self):
        self._result = None
        self._stop_listeners()
        self.root.destroy()
