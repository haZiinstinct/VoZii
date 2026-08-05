"""VoZii Settings — native dunkle Titelleiste, haZii Design."""

import logging
import os
import sys
import threading
import webbrowser

import customtkinter as ctk
from pynput import keyboard, mouse

from src import __url__, __version__
from src.theme import BRAND, FONT_BODY, FONT_MONO
from src.hotkey import key_to_name, mouse_button_to_name
from src.winutil import enable_dark_titlebar
from src.config import save_config
from src.i18n import DICTATION_LANGS, UI_LANGUAGES, set_language, t
from src.downloader import (
    is_binary_installed, is_model_installed, is_server_available,
    download_and_extract_binary, download_model, ensure_server_binary,
)
from src.text_processor import (
    get_ollama_state, install_ollama, pull_model,
    is_ollama_installed, start_ollama, stop_ollama, DEFAULT_MODEL,
    OLLAMA_TIERS, tier_for_model, size_label,
)

log = logging.getLogger(__name__)

ctk.set_appearance_mode("dark")

# Whisper-Modell-Key -> i18n-Key (Picker-Label). large-v3-turbo = modernes
# Diktat-Modell: nahezu beste Qualitaet, schnell, multilingual.
MODEL_LABEL_KEYS = {
    "tiny": "model.tiny",
    "large-v3-turbo-q5_0": "model.turbo_q5",
    "large-v3-turbo": "model.turbo",
}
# Legacy-Modelle nur zur Anzeige, falls ein Bestandsnutzer sie noch nutzt
LEGACY_MODEL_LABEL_KEYS = {
    "small": "model.legacy.small",
    "medium": "model.legacy.medium",
}
# Sichtbare Kurzbeschreibung je Modell (zuverlaessiger als Tooltips auf OptionMenu)
MODEL_DESC_KEYS = {
    "tiny": "model.desc.tiny",
    "large-v3-turbo-q5_0": "model.desc.turbo_q5",
    "large-v3-turbo": "model.desc.turbo",
    "small": "model.desc.small",
    "medium": "model.desc.medium",
}
# AI-Tier-ID -> i18n-Key
AITIER_LABEL_KEYS = {"fast": "aimodel.fast", "balanced": "aimodel.balanced", "best": "aimodel.best"}

# Gemeinsamer Stil fuer alle SegmentedButtons (Sprache/Transkription/Modus)
_SEG_STYLE = dict(
    font=(FONT_BODY, 13), selected_color=BRAND["cyan"],
    selected_hover_color=BRAND["cyan_dim"], unselected_color=BRAND["card"],
    unselected_hover_color=BRAND["card_hover"], text_color=BRAND["text_bright"],
    fg_color=BRAND["card"], corner_radius=8,
)


def _icon_path() -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "src", "vozii.ico")


def _fmt_eta(seconds: float) -> str:
    if seconds < 90:
        return f"~{int(seconds)} s"
    return f"~{int(round(seconds / 60))} min"


class Tooltip:
    """Hover-Tooltip im Card-Design (tkinter-Toplevel, randlos)."""

    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self._tip = None
        try:
            widget.bind("<Enter>", self._show, add="+")
            widget.bind("<Leave>", self._hide, add="+")
            widget.bind("<ButtonPress>", self._hide, add="+")
        except NotImplementedError:
            # CTkSegmentedButton & Co. unterstuetzen bind() nicht — dann eben
            # kein Tooltip fuer dieses Widget
            pass

    def _show(self, _e=None):
        if self._tip is not None:
            return
        import tkinter as tk
        self._tip = tk.Toplevel(self.widget)
        self._tip.overrideredirect(True)
        self._tip.attributes("-topmost", True)
        tk.Label(self._tip, text=self.text, bg=BRAND["card_hover"], fg=BRAND["text"],
                 font=(FONT_BODY, 10), justify="left", padx=10, pady=6,
                 wraplength=300).pack()
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._tip.geometry(f"+{x}+{y}")

    def _hide(self, _e=None):
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


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
        self._relaunch = False
        self._downloading = False
        self._cancel_download = threading.Event()
        self._ollama_busy = False
        self._ollama_cancel = None  # threading.Event during install/pull
        self._refresh_ollama_state()

    def _refresh_ollama_state(self):
        """Refresh Ollama status: ready / no_model / installed_not_running / not_installed."""
        required_model = self.config.get("ollama_model", DEFAULT_MODEL)
        self._ollama_state = get_ollama_state(required_model)

    def run(self):
        self.root = ctk.CTk()
        self.root.title("VoZii")
        self.root.configure(fg_color=BRAND["bg"])
        self.root.resizable(False, False)
        try:
            self.root.iconbitmap(_icon_path())
        except Exception:
            pass
        # Nativer Schliessen-Button (X) = Abbrechen
        self.root.protocol("WM_DELETE_WINDOW", self._cancel)

        w = 460
        h = min(760, self.root.winfo_screenheight() - 120)
        sx = (self.root.winfo_screenwidth() - w) // 2
        sy = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{sx}+{sy}")
        enable_dark_titlebar(self.root)

        # Branding-Kopfzeile + Sprachwaehler (🌐) rechts
        head = ctk.CTkFrame(self.root, fg_color="transparent")
        head.pack(fill="x", padx=24, pady=(14, 0))
        ctk.CTkLabel(head, text="VoZii", font=(FONT_MONO, 22, "bold"),
                     text_color=BRAND["cyan"]).pack(side="left")
        ctk.CTkLabel(head, text=f"v{__version__}", font=(FONT_MONO, 10),
                     text_color=BRAND["text_dim"]).pack(side="left", padx=(6, 0), pady=(6, 0))

        self._uilang_to_code = {name: code for code, name in UI_LANGUAGES.items()}
        cur_uilang = UI_LANGUAGES.get(self.config.get("ui_language", "de"), "Deutsch")
        ui_lang_menu = ctk.CTkOptionMenu(
            head, values=list(UI_LANGUAGES.values()),
            variable=ctk.StringVar(value=f"🌐 {cur_uilang}"),
            width=130, font=(FONT_BODY, 12), fg_color=BRAND["card"],
            button_color=BRAND["card_hover"], button_hover_color=BRAND["cyan_dim"],
            dropdown_fg_color=BRAND["card"], dropdown_hover_color=BRAND["card_hover"],
            dropdown_text_color=BRAND["text"], text_color=BRAND["text"], corner_radius=8,
            command=self._on_ui_language_change)
        ui_lang_menu.pack(side="right", pady=(2, 0))
        Tooltip(ui_lang_menu, t("header.ui_lang_tooltip"))

        # Backend-Info als Pill-Badge (hazii.org-Stil)
        badge = ctk.CTkFrame(self.root, fg_color=BRAND["card"], corner_radius=12,
                             border_width=1, border_color=BRAND["border"])
        badge.pack(anchor="w", padx=24, pady=(6, 10))
        ctk.CTkLabel(badge, text=f"{self.backend_name}  ·  {self.gpu_name or 'CPU'}",
                     font=(FONT_MONO, 11), text_color=BRAND["text_dim"]
                     ).pack(padx=10, pady=2)

        # Credit-Fusszeile "// code: haZii.org" — zuerst gepackt (side="bottom"),
        # sitzt daher ganz unten, der Start-Button landet darueber
        credit_bar = ctk.CTkFrame(self.root, fg_color="transparent")
        credit_bar.pack(side="bottom", pady=(0, 8))
        for txt, color, weight in (("// code: ", BRAND["text_dim"], "normal"),
                                   ("ha", BRAND["cyan"], "bold"),
                                   ("Z", BRAND["text_bright"], "bold"),
                                   ("ii", BRAND["cyan"], "bold"),
                                   (".org", BRAND["cyan_dim"], "bold")):
            lbl = ctk.CTkLabel(credit_bar, text=txt, font=(FONT_MONO, 12, weight),
                               text_color=color, cursor="hand2")
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda _e: webbrowser.open(__url__))

        # START-Button unten fixiert — bleibt immer sichtbar, egal wie viel
        # Inhalt darueber aufgeklappt ist
        start_bar = ctk.CTkFrame(self.root, fg_color="transparent")
        start_bar.pack(side="bottom", fill="x", padx=24, pady=(8, 8))
        ctk.CTkButton(start_bar, text=t("btn.start"), height=44, font=(FONT_BODY, 16, "bold"),
                      fg_color=BRAND["cyan"], text_color=BRAND["bg"],
                      hover_color=BRAND["cyan_dim"], corner_radius=10,
                      command=self._save).pack(fill="x")

        # Inhalt scrollbar zwischen Badge und Start-Button
        c = ctk.CTkScrollableFrame(self.root, fg_color="transparent")
        c.pack(fill="both", expand=True, padx=20)

        # HOTKEY
        self._heading(c, t("section.hotkey"))
        hk = ctk.CTkFrame(c, fg_color="transparent")
        hk.pack(fill="x", pady=(0, 14))
        self.hotkey_label = ctk.CTkLabel(hk, text=self.config["hotkey"].upper().replace("+", " + "),
                                         font=(FONT_MONO, 18, "bold"), text_color=BRAND["text_bright"])
        self.hotkey_label.pack(side="left")
        ctk.CTkButton(hk, text=t("btn.change"), width=80, height=30, font=(FONT_BODY, 12),
                      fg_color=BRAND["card"], text_color=BRAND["text"],
                      hover_color=BRAND["card_hover"], corner_radius=8,
                      border_width=1, border_color=BRAND["border"],
                      command=self._start_recording).pack(side="right")

        # MODELL + DOWNLOAD
        self._heading(c, t("section.model"))
        mr = ctk.CTkFrame(c, fg_color="transparent")
        mr.pack(fill="x", pady=(0, 4))
        # Aktuelle Stufen + (falls aktiv) das Legacy-Modell des Bestandsnutzers
        labels = {k: t(v) for k, v in MODEL_LABEL_KEYS.items()}
        cur_model = self.config["model_size"]
        if cur_model in LEGACY_MODEL_LABEL_KEYS:
            labels[cur_model] = t(LEGACY_MODEL_LABEL_KEYS[cur_model])
        self._model_label_to_key = {v: k for k, v in labels.items()}
        self.model_var = ctk.StringVar(
            value=labels.get(cur_model, labels["large-v3-turbo-q5_0"]))
        model_menu = ctk.CTkOptionMenu(mr, values=list(labels.values()), variable=self.model_var,
                          font=(FONT_BODY, 13),
                          width=260, fg_color=BRAND["card"], button_color=BRAND["card_hover"],
                          button_hover_color=BRAND["cyan_dim"], dropdown_fg_color=BRAND["card"],
                          dropdown_hover_color=BRAND["card_hover"], dropdown_text_color=BRAND["text"],
                          text_color=BRAND["text"], corner_radius=8,
                          command=self._on_model_change)
        model_menu.pack(side="left")
        self.dl_btn = ctk.CTkButton(mr, text=t("btn.download"), width=100, height=32,
                                     font=(FONT_BODY, 12, "bold"), fg_color=BRAND["cyan"],
                                     text_color=BRAND["bg"], hover_color=BRAND["cyan_dim"],
                                     corner_radius=8, command=self._download_current_model)
        self.dl_btn.pack(side="right")

        self.model_desc = ctk.CTkLabel(c, text="", font=(FONT_BODY, 11),
                                       text_color=BRAND["text_dim"], anchor="w")
        self.model_desc.pack(fill="x", pady=(0, 2))
        self._update_model_desc()

        self.progress = ctk.CTkProgressBar(c, progress_color=BRAND["cyan"],
                                            fg_color=BRAND["card"], height=4, corner_radius=2)
        self.progress.pack(fill="x", pady=(4, 2))
        self.progress.set(0)
        self.progress_text = ctk.CTkLabel(c, text="", font=(FONT_BODY, 11),
                                           text_color=BRAND["text_dim"], height=16)
        self.progress_text.pack(anchor="w", pady=(0, 10))
        self._update_dl_button()

        # DIKTAT-SPRACHE (Auto deckt alle ~99 Whisper-Sprachen ab)
        self._heading(c, t("section.language"))
        dic_labels = {t("lang.auto"): "auto"}
        for code, name in DICTATION_LANGS.items():
            dic_labels[name] = code
        self._diclang_label_to_code = dic_labels
        code_to_label = {v: k for k, v in dic_labels.items()}
        self.lang_var = ctk.StringVar(
            value=code_to_label.get(self.config.get("language", "auto"), t("lang.auto")))
        ctk.CTkOptionMenu(c, values=list(dic_labels), variable=self.lang_var, font=(FONT_BODY, 13),
                          fg_color=BRAND["card"], button_color=BRAND["card_hover"],
                          button_hover_color=BRAND["cyan_dim"], dropdown_fg_color=BRAND["card"],
                          dropdown_hover_color=BRAND["card_hover"], dropdown_text_color=BRAND["text"],
                          text_color=BRAND["text"], corner_radius=8).pack(fill="x", pady=(0, 14))

        # TRANSKRIPTION (Beam-Search: schnell vs. genau)
        self._heading(c, t("section.transcription"))
        self._perf_label_to_code = {t("perf.fast"): "speed", t("perf.accurate"): "quality"}
        perf_code_to_label = {v: k for k, v in self._perf_label_to_code.items()}
        self.perf_var = ctk.StringVar(
            value=perf_code_to_label.get(self.config.get("performance_mode", "speed"), t("perf.fast")))
        ctk.CTkSegmentedButton(c, values=list(self._perf_label_to_code), variable=self.perf_var,
                               **_SEG_STYLE).pack(fill="x", pady=(0, 2))
        ctk.CTkLabel(c, text=t("perf.desc"),
                     font=(FONT_BODY, 11), text_color=BRAND["text_dim"], anchor="w"
                     ).pack(fill="x", pady=(0, 14))

        # NACHBEARBEITUNG — einklappbar (optional, braucht Ollama)
        self._ollama_collapsed = self.config.get("post_processing_mode", "off") == "off"
        self._ollama_header = ctk.CTkFrame(c, fg_color="transparent", cursor="hand2")
        self._ollama_header.pack(fill="x", pady=(0, 4))
        self._ollama_arrow = ctk.CTkLabel(
            self._ollama_header, text="▾" if not self._ollama_collapsed else "▸",
            font=(FONT_BODY, 12, "bold"), text_color=BRAND["text_dim"], width=14)
        self._ollama_arrow.pack(side="left")
        header_lbl = ctk.CTkLabel(self._ollama_header, text=t("section.postproc").upper(),
                                  font=(FONT_BODY, 12, "bold"), text_color=BRAND["text_dim"])
        header_lbl.pack(side="left", padx=(4, 0))
        for widget in (self._ollama_header, self._ollama_arrow, header_lbl):
            widget.bind("<Button-1>", self._toggle_ollama_section)
        Tooltip(header_lbl, t("postproc.tooltip"))

        self.ollama_container = ctk.CTkFrame(c, fg_color="transparent")
        if not self._ollama_collapsed:
            self.ollama_container.pack(fill="x", after=self._ollama_header)

        self._mode_label_to_code = {t("mode.off"): "off", t("mode.smart"): "smart", t("mode.prompt"): "prompt"}
        mode_code_to_label = {v: k for k, v in self._mode_label_to_code.items()}
        self.mode_var = ctk.StringVar(
            value=mode_code_to_label.get(self.config.get("post_processing_mode", "off"), t("mode.off")))
        self.mode_btn = ctk.CTkSegmentedButton(
            self.ollama_container, values=list(self._mode_label_to_code),
            variable=self.mode_var, **_SEG_STYLE,
        )
        self.mode_btn.pack(fill="x", pady=(0, 2))
        ctk.CTkLabel(self.ollama_container, text=t("mode.desc"),
                     font=(FONT_BODY, 11), text_color=BRAND["text_dim"], anchor="w",
                     wraplength=400, justify="left").pack(fill="x", pady=(0, 4))

        # KI-Modell-Picker (Stufen lokalisiert, intern stabile IDs)
        self._tier_label_to_id = {t(v): k for k, v in AITIER_LABEL_KEYS.items()}
        tier_id_to_label = {k: t(v) for k, v in AITIER_LABEL_KEYS.items()}
        self.ollama_tier_var = ctk.StringVar(
            value=tier_id_to_label.get(tier_for_model(self.config.get("ollama_model", DEFAULT_MODEL)),
                                       t("aimodel.balanced")))
        tier_btn = ctk.CTkSegmentedButton(
            self.ollama_container, values=list(self._tier_label_to_id),
            variable=self.ollama_tier_var, command=self._on_ollama_tier_change, **_SEG_STYLE,
        )
        tier_btn.pack(fill="x", pady=(0, 2))
        ctk.CTkLabel(self.ollama_container, text=t("aimodel.desc"),
                     font=(FONT_BODY, 11), text_color=BRAND["text_dim"], anchor="w",
                     wraplength=400, justify="left").pack(fill="x", pady=(0, 4))

        # Ollama Status-Row: Label + Mini-Button (Start/Stop)
        self.ollama_status_row = ctk.CTkFrame(self.ollama_container, fg_color="transparent")
        self.ollama_status_row.pack(fill="x", pady=(0, 2))

        self.ollama_status_label = ctk.CTkLabel(
            self.ollama_status_row, text="", font=(FONT_BODY, 11),
            text_color=BRAND["text_dim"], anchor="w",
        )
        self.ollama_status_label.pack(side="left", fill="x", expand=True)

        self.ollama_mini_btn = ctk.CTkButton(
            self.ollama_status_row, text="", width=28, height=22,
            font=(FONT_MONO, 11),
            fg_color="transparent", text_color=BRAND["text_dim"],
            border_width=1, border_color=BRAND["border"],
            hover_color=BRAND["card_hover"], corner_radius=6,
            command=self._handle_ollama_mini_btn,
        )
        # Wird in _render_ollama_section() gepackt je nach state

        Tooltip(self.ollama_mini_btn, t("ollama.mini.tooltip"))

        # Action-Button (Install/Start/Pull) - nur wenn noetig
        self.ollama_action_btn = ctk.CTkButton(
            self.ollama_container, text="", height=34, font=(FONT_BODY, 13, "bold"),
            fg_color=BRAND["cyan"], text_color=BRAND["bg"],
            hover_color=BRAND["cyan_dim"], corner_radius=8,
            command=self._handle_ollama_action,
        )

        # Download-Container (erscheint waehrend Install/Pull)
        self.ollama_dl_frame = ctk.CTkFrame(self.ollama_container, fg_color="transparent")

        # Grosse Prozent-Anzeige
        self.ollama_percent_label = ctk.CTkLabel(
            self.ollama_dl_frame, text="0%",
            font=(FONT_MONO, 20, "bold"), text_color=BRAND["cyan"],
        )
        self.ollama_percent_label.pack(anchor="w")

        # Progress-Bar (groesser)
        self.ollama_progress = ctk.CTkProgressBar(
            self.ollama_dl_frame, progress_color=BRAND["cyan"],
            fg_color=BRAND["card"], height=8, corner_radius=4,
        )
        self.ollama_progress.pack(fill="x", pady=(2, 4))
        self.ollama_progress.set(0)

        # Detail-Zeile: "650 MB / 2 GB · 12 MB/s · Status"
        self.ollama_detail_label = ctk.CTkLabel(
            self.ollama_dl_frame, text="",
            font=(FONT_BODY, 11), text_color=BRAND["text_dim"],
        )
        self.ollama_detail_label.pack(anchor="w", pady=(0, 6))

        # Cancel-Button
        self.ollama_cancel_btn = ctk.CTkButton(
            self.ollama_dl_frame, text=t("btn.cancel"),
            height=30, font=(FONT_BODY, 12),
            fg_color="transparent", text_color=BRAND["text_dim"],
            border_width=1, border_color=BRAND["border"],
            hover_color=BRAND["red"], corner_radius=8,
            command=self._cancel_ollama_action,
        )
        self.ollama_cancel_btn.pack(fill="x")

        self._render_ollama_section()
        # Spacer nach Section
        self._ollama_spacer = ctk.CTkFrame(c, fg_color="transparent", height=14)
        self._ollama_spacer.pack()

        # MIKROFON
        self._heading(c, t("section.microphone"))
        devs = [t("mic.default")] + [d["name"] for d in self.available_devices]
        cur_dev = t("mic.default")
        if self.config.get("audio_device"):
            for d in self.available_devices:
                if d["name"] == self.config["audio_device"]:
                    cur_dev = d["name"]
                    break
        self.mic_var = ctk.StringVar(value=cur_dev)
        mic_row = ctk.CTkFrame(c, fg_color="transparent")
        mic_row.pack(fill="x", pady=(0, 4))
        ctk.CTkOptionMenu(mic_row, values=devs, variable=self.mic_var, font=(FONT_BODY, 13),
                          width=280, fg_color=BRAND["card"], button_color=BRAND["card_hover"],
                          button_hover_color=BRAND["cyan_dim"], dropdown_fg_color=BRAND["card"],
                          dropdown_hover_color=BRAND["card_hover"], dropdown_text_color=BRAND["text"],
                          text_color=BRAND["text"], corner_radius=8).pack(side="left")
        self._mic_testing = False
        self.mic_test_btn = ctk.CTkButton(
            mic_row, text=t("btn.test"), width=80, height=30, font=(FONT_BODY, 12),
            fg_color=BRAND["card"], text_color=BRAND["text"],
            hover_color=BRAND["card_hover"], corner_radius=8,
            border_width=1, border_color=BRAND["border"],
            command=self._test_microphone)
        self.mic_test_btn.pack(side="right")
        Tooltip(self.mic_test_btn, t("mic.tooltip"))

        # Live-Pegel waehrend des Tests
        self.mic_level = ctk.CTkProgressBar(c, progress_color=BRAND["cyan"],
                                            fg_color=BRAND["card"], height=4, corner_radius=2)
        self.mic_level.pack(fill="x", pady=(4, 2))
        self.mic_level.set(0)
        self.mic_test_label = ctk.CTkLabel(c, text="", font=(FONT_BODY, 11),
                                           text_color=BRAND["text_dim"], height=16)
        self.mic_test_label.pack(anchor="w", pady=(0, 10))

        # OPTIONS
        self.overlay_var = ctk.BooleanVar(value=self.config.get("show_overlay", True))
        ov_switch = ctk.CTkSwitch(c, text=t("opt.overlay"), variable=self.overlay_var,
                      font=(FONT_BODY, 13), text_color=BRAND["text"],
                      progress_color=BRAND["cyan"], button_color=BRAND["text_dim"],
                      button_hover_color=BRAND["text"])
        ov_switch.pack(anchor="w", pady=(0, 6))
        Tooltip(ov_switch, t("opt.overlay.tooltip"))

        self.sound_var = ctk.BooleanVar(value=self.config.get("audio_feedback", True))
        ctk.CTkSwitch(c, text=t("opt.sound"), variable=self.sound_var,
                      font=(FONT_BODY, 13), text_color=BRAND["text"],
                      progress_color=BRAND["cyan"], button_color=BRAND["text_dim"],
                      button_hover_color=BRAND["text"]).pack(anchor="w", pady=(0, 6))

        self.clipres_var = ctk.BooleanVar(value=self.config.get("restore_clipboard", True))
        clip_switch = ctk.CTkSwitch(c, text=t("opt.clipboard"), variable=self.clipres_var,
                      font=(FONT_BODY, 13), text_color=BRAND["text"],
                      progress_color=BRAND["cyan"], button_color=BRAND["text_dim"],
                      button_hover_color=BRAND["text"])
        clip_switch.pack(anchor="w", pady=(0, 6))
        Tooltip(clip_switch, t("opt.clipboard.tooltip"))

        self.autostart_var = ctk.BooleanVar(value=self.config.get("auto_start", False))
        ctk.CTkSwitch(c, text=t("opt.autostart"), variable=self.autostart_var,
                      font=(FONT_BODY, 13), text_color=BRAND["text"],
                      progress_color=BRAND["cyan"], button_color=BRAND["text_dim"],
                      button_hover_color=BRAND["text"]).pack(anchor="w", pady=(0, 6))

        # Historie: Switch + Loeschen-Button (zweistufig statt Dialog)
        self.history_var = ctk.BooleanVar(value=self.config.get("history_enabled", True))
        hist_row = ctk.CTkFrame(c, fg_color="transparent")
        hist_row.pack(fill="x", pady=(0, 16))
        ctk.CTkSwitch(hist_row, text=t("opt.history"), variable=self.history_var,
                      font=(FONT_BODY, 13), text_color=BRAND["text"],
                      progress_color=BRAND["cyan"], button_color=BRAND["text_dim"],
                      button_hover_color=BRAND["text"]).pack(side="left")
        self._hist_confirm = False
        self.hist_clear_btn = ctk.CTkButton(
            hist_row, text=self._hist_clear_label(), width=110, height=26,
            font=(FONT_BODY, 11), fg_color="transparent",
            text_color=BRAND["text_dim"], border_width=1,
            border_color=BRAND["border"], hover_color=BRAND["card_hover"],
            corner_radius=8, command=self._clear_history)
        self.hist_clear_btn.pack(side="right")

        self.root.mainloop()
        if self._relaunch:
            self._relaunch = False
            return self.run()  # Sprache gewechselt -> Fenster neu aufbauen
        return self._result

    # --- Mikrofontest ---

    def _test_microphone(self):
        """3s aufnehmen, Live-Pegel zeigen, Ergebnis melden."""
        if self._mic_testing:
            return
        self._mic_testing = True
        self.mic_test_btn.configure(state="disabled", text=t("mic.testing"))
        self.mic_test_label.configure(text=t("mic.speak_now"), text_color=BRAND["text_dim"])

        device_index = None
        if self.mic_var.get() != t("mic.default"):
            for d in self.available_devices:
                if d["name"] == self.mic_var.get():
                    device_index = d["index"]
                    break

        def run():
            import time

            import numpy as np
            import sounddevice as sd

            peak = [0.0]

            def cb(indata, frames, t, status):
                rms = float(np.sqrt(np.mean(np.square(indata))))
                peak[0] = max(peak[0], rms)
                # 0.125 rms ~ Vollausschlag; normale Sprache landet gut sichtbar
                level = min(1.0, rms * 8)
                self.root.after(0, lambda v=level: self.mic_level.set(v))

            try:
                with sd.InputStream(device=device_index, channels=1,
                                    dtype="float32", callback=cb):
                    time.sleep(3)
                if peak[0] > 0.005:
                    msg, color = t("mic.signal_ok"), BRAND["green"]
                else:
                    msg, color = t("mic.no_signal"), BRAND["red"]
            except Exception as e:
                msg, color = t("mic.error", error=e), BRAND["red"]
            self.root.after(0, lambda: self._mic_test_done(msg, color))

        threading.Thread(target=run, daemon=True).start()

    def _mic_test_done(self, msg, color):
        self._mic_testing = False
        self.mic_test_btn.configure(state="normal", text=t("btn.test"))
        self.mic_test_label.configure(text=msg, text_color=color)
        self.mic_level.set(0)

    def _on_ui_language_change(self, _native):
        """Oberflaechen-Sprache wechseln: speichern + Fenster neu aufbauen."""
        code = self._uilang_to_code.get(_native.replace("🌐 ", ""), "de")
        if code == self.config.get("ui_language"):
            return
        self._collect_into_config()
        self.config["ui_language"] = code
        try:
            save_config(self.config)
        except Exception:
            log.exception("ui_language speichern fehlgeschlagen")
        set_language(code)
        self._relaunch = True
        self._stop_listeners()
        self.root.destroy()

    def _collect_into_config(self):
        """Aktuelle Widget-Werte in self.config uebernehmen (vor Sprach-Rebuild)."""
        self.config.update({
            "language": self._diclang_label_to_code.get(self.lang_var.get(), "auto"),
            "model_size": self._get_model_size(),
            "show_overlay": self.overlay_var.get(),
            "auto_start": self.autostart_var.get(),
            "audio_device": None if self.mic_var.get() == t("mic.default") else self.mic_var.get(),
            "post_processing_mode": self._mode_label_to_code.get(self.mode_var.get(), "off"),
            "performance_mode": self._perf_label_to_code.get(self.perf_var.get(), "speed"),
            "history_enabled": self.history_var.get(),
            "audio_feedback": self.sound_var.get(),
            "restore_clipboard": self.clipres_var.get(),
        })

    def _on_ollama_tier_change(self, label):
        """Picker -> Modell-Tag setzen, Status (ready/no_model) neu berechnen."""
        tier_id = self._tier_label_to_id.get(label, "balanced")
        self.config["ollama_model"] = OLLAMA_TIERS[tier_id][0]
        self._refresh_ollama_state()
        self._render_ollama_section()

    def _toggle_ollama_section(self, _e=None):
        self._ollama_collapsed = not self._ollama_collapsed
        if self._ollama_collapsed:
            self.ollama_container.pack_forget()
            self._ollama_arrow.configure(text="▸")
        else:
            self.ollama_container.pack(fill="x", after=self._ollama_header)
            self._ollama_arrow.configure(text="▾")

    def _hist_clear_label(self) -> str:
        from src.history import TranscriptionHistory
        try:
            return t("hist.clear", count=TranscriptionHistory().count())
        except Exception:
            return t("hist.clear_plain")

    def _clear_history(self):
        """Zweistufig: erster Klick fragt, zweiter loescht."""
        from src.history import TranscriptionHistory
        if not self._hist_confirm:
            self._hist_confirm = True
            self.hist_clear_btn.configure(text=t("hist.confirm"), text_color=BRAND["red"],
                                          border_color=BRAND["red"])
            return
        try:
            TranscriptionHistory().clear()
        except Exception:
            log.exception("Historie loeschen fehlgeschlagen")
        self._hist_confirm = False
        self.hist_clear_btn.configure(text=self._hist_clear_label(),
                                      text_color=BRAND["text_dim"],
                                      border_color=BRAND["border"])

    def _heading(self, parent, text):
        ctk.CTkLabel(parent, text=text.upper(), font=(FONT_BODY, 12, "bold"),
                     text_color=BRAND["text_dim"]).pack(anchor="w", pady=(0, 4))

    # Model
    def _get_model_size(self):
        return self._model_label_to_key.get(self.model_var.get(), "large-v3-turbo-q5_0")

    def _on_model_change(self, _):
        self._update_model_desc()
        self._update_dl_button()

    def _update_model_desc(self):
        key = MODEL_DESC_KEYS.get(self._get_model_size())
        self.model_desc.configure(text=t(key) if key else "")

    def _update_dl_button(self):
        ok = is_binary_installed() and is_model_installed(self._get_model_size())
        if ok and not is_server_available():
            # Bestandsnutzer: whisper-server.exe fehlt noch (beschleunigt
            # Transkription deutlich) — als Update anbieten
            self.dl_btn.configure(text=t("btn.update"), state="normal",
                                  fg_color=BRAND["cyan"], text_color=BRAND["bg"])
        elif ok:
            self.dl_btn.configure(text=t("btn.ready"), state="disabled",
                                  fg_color=BRAND["card"], text_color=BRAND["green"])
        else:
            self.dl_btn.configure(text=t("btn.download"), state="normal",
                                  fg_color=BRAND["cyan"], text_color=BRAND["bg"])

    def _download_current_model(self):
        if self._downloading:
            self._cancel_download.set()
            self._downloading = False
            return

        size = self._get_model_size()
        self._downloading = True
        self._cancel_download.clear()
        self.dl_btn.configure(text=t("btn.cancel"), fg_color=BRAND["red"], hover_color="#dc2626")

        def run():
            try:
                if not is_binary_installed():
                    self._msg(t("download.whisper"))
                    download_and_extract_binary(self.gpu_type, self._checked_progress)
                elif not is_server_available():
                    self._msg(t("download.server"))
                    ensure_server_binary(self.gpu_type, self._checked_progress)
                if self._cancel_download.is_set(): raise InterruptedError
                if not is_model_installed(size):
                    self._msg(t("download.model", model=size))
                    download_model(size, self._checked_progress)
                if self._cancel_download.is_set(): raise InterruptedError
                self.root.after(0, self._dl_done)
            except InterruptedError:
                self.root.after(0, lambda: self._dl_fail(t("download.cancelled")))
            except Exception as e:
                # str(e) vor dem Lambda binden — e ist nach dem except-Block weg
                msg = str(e)
                self.root.after(0, lambda m=msg: self._dl_fail(m))
            finally:
                self._downloading = False

        threading.Thread(target=run, daemon=True).start()

    def _checked_progress(self, dl, total, speed_bps=0):
        if self._cancel_download.is_set(): raise InterruptedError
        f = dl / total if total else 0
        eta = ""
        if speed_bps > 0 and total > dl:
            eta = f"  ·  {speed_bps / 1048576:.1f} MB/s  ·  {_fmt_eta((total - dl) / speed_bps)}"
        text = f"{dl // 1048576} / {total // 1048576} MB{eta}"
        self.root.after(0, lambda: self.progress.set(f))
        self.root.after(0, lambda: self.progress_text.configure(text=text))

    def _msg(self, t):
        self.root.after(0, lambda: self.progress_text.configure(text=t, text_color=BRAND["text_dim"]))

    def _dl_done(self):
        self.progress.set(1.0)
        hotkey = self.config.get("hotkey", "ctrl+shift+space").upper().replace("+", " + ")
        self.progress_text.configure(text=t("download.done", hotkey=hotkey),
                                     text_color=BRAND["green"])
        self._update_dl_button()

    def _dl_fail(self, msg):
        self.progress.set(0)
        self.progress_text.configure(text=msg, text_color=BRAND["red"])
        self._update_dl_button()

    # --- Ollama Section Rendering + Handlers ---

    def _render_ollama_section(self):
        """Rendert UI je nach State: ready/no_model/installed_not_running/not_installed/busy."""
        required = self.config.get("ollama_model", DEFAULT_MODEL)

        if self._ollama_busy:
            # Waehrend Install/Pull: zeige Download-Frame
            self.ollama_status_row.pack_forget()
            self.ollama_action_btn.pack_forget()
            if not self.ollama_dl_frame.winfo_ismapped():
                self.ollama_dl_frame.pack(fill="x", pady=(4, 0))
            return

        # Nicht busy: Download-Frame verstecken
        if self.ollama_dl_frame.winfo_ismapped():
            self.ollama_dl_frame.pack_forget()

        # Status-Row wieder zeigen
        if not self.ollama_status_row.winfo_ismapped():
            self.ollama_status_row.pack(fill="x", pady=(0, 2))

        state = self._ollama_state

        # Mini-Button State: ▶ fuer Start, ■ fuer Stop, versteckt bei not_installed
        if state in ("ready", "no_model"):
            self.ollama_mini_btn.configure(
                text="■", text_color=BRAND["text_dim"], hover_color=BRAND["red"],
            )
            if not self.ollama_mini_btn.winfo_ismapped():
                self.ollama_mini_btn.pack(side="right", padx=(6, 0))
        elif state == "installed_not_running":
            self.ollama_mini_btn.configure(
                text="▶", text_color=BRAND["text_dim"], hover_color=BRAND["green"],
            )
            if not self.ollama_mini_btn.winfo_ismapped():
                self.ollama_mini_btn.pack(side="right", padx=(6, 0))
        else:
            self.ollama_mini_btn.pack_forget()

        if state == "ready":
            self.ollama_status_label.configure(
                text=t("ollama.status.ready", model=required), text_color=BRAND["green"])
            self.mode_btn.configure(state="normal")
            self.ollama_action_btn.pack_forget()

        elif state == "no_model":
            self.ollama_status_label.configure(
                text=t("ollama.status.no_model", model=required), text_color=BRAND["text_dim"])
            self.mode_btn.configure(state="disabled")
            self.mode_var.set(t("mode.off"))
            self.ollama_action_btn.configure(text=t("ollama.action.load_model", size=size_label(required)))
            if not self.ollama_action_btn.winfo_ismapped():
                self.ollama_action_btn.pack(fill="x", pady=(4, 0))

        elif state == "installed_not_running":
            self.ollama_status_label.configure(
                text=t("ollama.status.not_running"), text_color=BRAND["amber"])
            self.mode_btn.configure(state="disabled")
            self.mode_var.set(t("mode.off"))
            self.ollama_action_btn.pack_forget()

        else:  # not_installed
            self.ollama_status_label.configure(
                text=t("ollama.status.not_installed"), text_color=BRAND["text_dim"])
            self.mode_btn.configure(state="disabled")
            self.mode_var.set(t("mode.off"))
            self.ollama_action_btn.configure(text=t("ollama.action.install"))
            if not self.ollama_action_btn.winfo_ismapped():
                self.ollama_action_btn.pack(fill="x", pady=(4, 0))

    def _handle_ollama_mini_btn(self):
        """Mini-Button: Start (wenn nicht gestartet) oder Stop (wenn laeuft)."""
        if self._ollama_busy:
            return
        state = self._ollama_state
        if state == "installed_not_running":
            self._handle_ollama_start()
        elif state in ("ready", "no_model"):
            stop_ollama()
            self._refresh_ollama_state()
            self._render_ollama_section()

    def _handle_ollama_action(self):
        """Dispatcht auf Start/Install/Pull je nach State."""
        if self._ollama_busy:
            return

        state = self._ollama_state

        if state == "installed_not_running":
            self._handle_ollama_start()
            return

        # Install oder Pull → busy + cancel_event
        self._ollama_busy = True
        self._ollama_cancel = threading.Event()
        self._render_ollama_section()
        self._update_ollama_progress(0, 0, t("progress.starting"), 0)

        required = self.config.get("ollama_model", DEFAULT_MODEL)

        def run():
            try:
                if state == "not_installed":
                    install_ollama(
                        progress_callback=self._on_ollama_progress,
                        cancel_event=self._ollama_cancel,
                    )
                    if self._ollama_cancel.is_set():
                        raise InterruptedError
                    pull_model(
                        required,
                        progress_callback=self._on_ollama_progress,
                        cancel_event=self._ollama_cancel,
                    )
                elif state == "no_model":
                    pull_model(
                        required,
                        progress_callback=self._on_ollama_progress,
                        cancel_event=self._ollama_cancel,
                    )
                self.root.after(0, self._ollama_action_done)
            except InterruptedError:
                self.root.after(0, lambda: self._ollama_action_fail(t("download.cancelled")))
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda m=msg: self._ollama_action_fail(m))

        threading.Thread(target=run, daemon=True).start()

    def _handle_ollama_start(self):
        """Ollama starten — kein Download-UI, nur Status-Text."""
        # KEIN _ollama_busy=True → kein Layout-Shift
        self.ollama_mini_btn.configure(state="disabled")
        self.ollama_status_label.configure(text=t("ollama.status.starting"), text_color=BRAND["amber"])

        def run():
            ollama_path = is_ollama_installed()
            if not ollama_path:
                self.root.after(0, lambda: self._on_start_done(False, t("ollama.not_found")))
                return
            ok = start_ollama(ollama_path)
            self.root.after(0, lambda: self._on_start_done(ok, None))

        threading.Thread(target=run, daemon=True).start()

    def _on_start_done(self, ok: bool, err: str | None):
        """Callback nach Ollama-Start."""
        self.ollama_mini_btn.configure(state="normal")
        self._refresh_ollama_state()
        self._render_ollama_section()
        if not ok and err:
            self.ollama_status_label.configure(text=t("error.generic", error=err), text_color=BRAND["red"])

    def _cancel_ollama_action(self):
        """User klickt Cancel - setzt das Event."""
        if self._ollama_cancel is not None:
            self._ollama_cancel.set()
            self.ollama_cancel_btn.configure(text=t("ollama.cancelling"), state="disabled")

    def _on_ollama_progress(self, completed, total, status, speed):
        """Thread-safe Progress-Update."""
        self.root.after(0, lambda: self._update_ollama_progress(completed, total, status, speed))

    def _update_ollama_progress(self, completed, total, status, speed):
        """Aktualisiert Download-UI: %, Progress-Bar, Detail-Zeile."""
        if total > 0:
            frac = completed / total
            percent = int(frac * 100)
            mb_done = completed // 1048576
            mb_total = total // 1048576
            if speed > 0:
                speed_mb = speed / 1048576
                detail = f"{mb_done} / {mb_total} MB  ·  {speed_mb:.1f} MB/s  ·  {status}"
            else:
                detail = f"{mb_done} / {mb_total} MB  ·  {status}"
        else:
            frac = 0
            percent = 0
            detail = status

        self.ollama_percent_label.configure(text=f"{percent}%")
        self.ollama_progress.set(frac)
        self.ollama_detail_label.configure(text=detail)

    def _ollama_action_done(self):
        self._ollama_busy = False
        self._ollama_cancel = None
        self.ollama_cancel_btn.configure(text=t("btn.cancel"), state="normal")
        self._refresh_ollama_state()
        self._render_ollama_section()

    def _ollama_action_fail(self, msg):
        self._ollama_busy = False
        self._ollama_cancel = None
        self.ollama_cancel_btn.configure(text=t("btn.cancel"), state="normal")
        self._refresh_ollama_state()
        self._render_ollama_section()
        self.ollama_status_label.configure(text=t("error.generic", error=msg), text_color=BRAND["red"])

    # Hotkey Recording
    def _start_recording(self):
        self._recording_hotkey = True
        self._pressed_keys = set()
        self._current_combo = []
        self.hotkey_label.configure(text=t("hotkey.press"), text_color=BRAND["amber"])
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
        # Validierung: ohne Binary + Modell laeuft nichts — nicht erst beim
        # Start crashen, sondern hier klar sagen was fehlt
        if not (is_binary_installed() and is_model_installed(self._get_model_size())):
            self._dl_fail(t("validate.model_missing"))
            return
        self._collect_into_config()
        self._result = self.config
        self._stop_listeners()
        self.root.destroy()

    def _cancel(self):
        self._result = None
        self._stop_listeners()
        self.root.destroy()
