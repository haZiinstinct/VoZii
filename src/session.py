"""Laufzeit eines Zyklus: Hotkey <-> Recorder <-> Transkriptions-Worker.

Aus app._run_cycle herausgezogen, damit diese Nahtstelle testbar ist — alle
Logikfehler des Audits (Oktober 2026) lagen hier. Abhaengigkeiten werden
injiziert; _run_cycle baut nur zusammen, startet die Threads und raeumt auf.
"""

import logging
import os
import queue
import threading

from src.filters import is_hallucination
from src.i18n import t
from src.state import AppState
from src.text_inserter import insert_text
from src.transcriber import TranscriptionTimeout

log = logging.getLogger(__name__)


class RunSession:
    def __init__(self, *, config: dict, state, recorder, transcriber, text_processor,
                 history=None, overlay=None, play_tone=None, show_error=None,
                 insert=insert_text, shutdown_event: threading.Event | None = None):
        self.config = config
        self.state = state
        self.recorder = recorder
        self.transcriber = transcriber
        self.text_processor = text_processor
        self.history = history
        self.overlay = overlay
        self._play_tone = play_tone
        self._show_error = show_error or (lambda title, msg: None)
        self._insert = insert
        self.use_sound = config.get("audio_feedback", True)
        self.audio_queue = queue.Queue()
        self.shutdown_event = shutdown_event or threading.Event()
        # Wird nach dem Erzeugen gesetzt — der Auto-Stop-Callback kann erst
        # nach dem Start einer Aufnahme feuern
        self.hotkey_mgr = None
        self._error_count = 0
        self._hint_shown = False

    # --- Feedback ---

    def _tone(self, freq: int, duration_ms: int):
        if self._play_tone:
            threading.Thread(target=self._play_tone, args=(freq, duration_ms),
                             daemon=True).start()

    def beep_start(self):
        if self.use_sound:
            self._tone(600, 80)

    def beep_done(self):
        if self.use_sound:
            self._tone(880, 60)

    def notify(self, code: str, duration_ms: int = 5000):
        """Kurzes visuelles Feedback (Status-Code im Overlay).

        Ohne Overlay waeren Fehler unsichtbar — dann wenigstens ein tiefer Ton."""
        if self.overlay:
            self.overlay.flash(code, duration_ms)
        elif code.startswith("err") and self.use_sound:
            self._tone(300, 250)

    # --- Hotkey-Callbacks ---

    def on_activate(self):
        try:
            if self.state.state == AppState.TRANSCRIBING:
                return
            self.state.set_state(AppState.RECORDING)
            self.beep_start()
            self.recorder.start_recording()
            log.info("Aufnahme gestartet")
        except Exception:
            log.exception("on_activate fehlgeschlagen")
            self.state.set_state(AppState.IDLE)
            self.notify("err_mic")

    def on_deactivate(self):
        try:
            if self.state.state != AppState.RECORDING:
                log.debug("on_deactivate ignoriert (State: %s)", self.state.state.value)
                return
            wav_path, duration, rms = self.recorder.stop_recording()
            if wav_path:
                self.state.set_state(AppState.TRANSCRIBING)
                self.audio_queue.put((wav_path, duration, rms))
            elif duration == 0 and not self.recorder.is_stream_healthy():
                # Kein einziges Sample vom Mikrofon. Frueher passierte
                # hier gar nichts — der Nutzer druckte den Hotkey und
                # bekam kein Zeichen, dass etwas kaputt ist.
                self.state.set_state(AppState.IDLE)
                log.error("Aufnahme ohne Audiodaten — Mikrofon-Stream tot")
                self.notify("err_mic")
                self.recorder.ensure_stream()
            else:
                self.state.set_state(AppState.IDLE)
                self.notify("short", 2000)
        except Exception:
            log.exception("on_deactivate fehlgeschlagen")
            self.state.set_state(AppState.IDLE)
            self.notify("err_mic")

    # Auto-Stop bei Stille (nur Toggle-Modus): wirkt wie der zweite
    # Hotkey-Druck — ueber den HotkeyManager, damit dessen Zustand mitgeht
    # und der Stopp im Dispatcher-Thread laeuft statt im PortAudio-Callback
    def auto_stop(self):
        if self.hotkey_mgr is not None:
            self.hotkey_mgr.deactivate()
        else:
            self.on_deactivate()

    def install_auto_stop(self):
        auto_stop_s = self.config.get("auto_stop_silence_s", 0)
        if self.config.get("mode") == "toggle" and auto_stop_s:
            self.recorder.set_auto_stop(auto_stop_s, self.auto_stop)
            log.info("Auto-Stop bei Stille: %.1fs", auto_stop_s)

    # --- Transkription ---

    def process(self, wav_path: str, duration: float, rms: float):
        """Eine Aufnahme transkribieren, einfuegen, WAV loeschen, zurueck auf IDLE."""
        try:
            text = self.transcriber.transcribe(wav_path)
            pop_notice = getattr(self.transcriber, "pop_notice", None)
            if pop_notice and pop_notice() == "cpu_fallback":
                # GPU-Backend abgestuerzt, laeuft ab jetzt auf der CPU
                self.notify("cpu_fallback", 4000)
            if text and is_hallucination(text, duration, rms):
                log.info("Halluzination verworfen (%.1fs, rms %.4f): %r",
                         duration, rms, text)
                text = ""
            if text:
                text = self.text_processor.process(text)
            if text:
                log.info("Transkribiert: %d Zeichen", len(text))
                if self.history:
                    self.history.add(text)
                inserted = self._insert(
                    text, restore_clipboard=self.config.get("restore_clipboard", True))
                if inserted:
                    self.beep_done()
                else:
                    # Text liegt in der Zwischenablage — Nutzer informieren
                    self.notify("clip")
                self._error_count = 0
            else:
                log.warning("Transkription leer")
                # Erklaerbarer Backend-Fehler (SAC-Block, fehlende
                # VC++-Runtime)? Einmal pro Zyklus als Dialog zeigen —
                # sonst raetselt der Nutzer ueber leere Diktate.
                hint = self.transcriber.last_error_hint
                if hint and not self._hint_shown:
                    self._hint_shown = True
                    self._show_error(t("dialog.backend_blocked.title"), hint)
                self.notify("empty", 2000)
        except TranscriptionTimeout:
            log.warning("Transkription im Timeout (%.1fs Audio) — verworfen", duration)
            self.notify("too_long")
        except Exception:
            log.exception("Transkription fehlgeschlagen")
            self._error_count += 1
            if self._error_count >= 2:
                self.notify("err_whisper")
                self._error_count = 0
        finally:
            try:
                os.remove(wav_path)
            except OSError:
                pass
        self.state.set_state(AppState.IDLE)

    def transcription_worker(self):
        while not self.shutdown_event.is_set():
            try:
                wav_path, duration, rms = self.audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self.process(wav_path, duration, rms)

    # --- Watchdog ---

    def health_check(self):
        """Haelt die zwei Dinge am Leben, die ueber Stunden still sterben:

        - Low-Level-Hooks: Windows entfernt sie bei Hook-Timeout, danach
          waere der Hotkey bis zum App-Neustart tot.
        - Audio-Stream: USB-Mikro kurz weg oder Windows-Audio-Engine neu
          gestartet — PortAudio meldet das nicht, `active` bleibt True,
          es kommen nur keine Samples mehr.
        """
        try:
            if not self.hotkey_mgr.is_healthy():
                log.warning("Hotkey-Listener tot — starte neu")
                self.hotkey_mgr.restart()
            else:
                self.hotkey_mgr.release_if_stuck()
        except Exception:
            log.exception("Hotkey-Watchdog fehlgeschlagen")
        try:
            if self.state.state == AppState.IDLE:
                self.recorder.ensure_stream()
        except Exception:
            log.exception("Audio-Watchdog fehlgeschlagen")

    def health_watchdog(self, interval_s: float):
        while not self.shutdown_event.wait(interval_s):
            self.health_check()
