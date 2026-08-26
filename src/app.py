"""VoZii App-Kern — Hauptschleife, Zyklus-Aufbau, Autostart.

Wird vom Thin-Launcher src/main.py importiert; crasht hier schon der Import,
faengt der Launcher das ab (Notfall-Log + nativer Dialog)."""

import logging
import os
import queue
import sys
import threading
import time

from src import __version__
from src.paths import TMP_DIR
from src.logger import setup_logging, acquire_single_instance, get_log_path
from src.state import AppState, StateManager
from src.config import load_config, save_config
from src.audio import AudioRecorder
from src.errors import VCREDIST_URL, check_vcredist
from src.transcriber import Transcriber, is_setup_complete
from src.text_inserter import insert_text
from src.hotkey import HotkeyManager
from src.tray import TrayApp
from src.settings_gui import SettingsWindow
from src.hardware import detect_gpu_cached, get_backend_name
from src.overlay import RecordingOverlay
from src.text_processor import TextProcessor
from src.filters import is_hallucination
from src.history import TranscriptionHistory
from src.i18n import set_language, t

log = logging.getLogger(__name__)


def show_error(title: str, msg: str):
    """Zeigt Error-Dialog UND loggt ihn."""
    log.error("%s: %s", title, msg)
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, msg)
        root.destroy()
    except Exception:
        pass


def play_tone(freq: int, duration_ms: int):
    try:
        import winsound
        winsound.Beep(freq, duration_ms)
    except Exception:
        pass


def _enable_dpi_awareness():
    """Per-Monitor-V2-DPI, sonst unscharfes/falsch skaliertes Overlay auf High-DPI.

    CustomTkinter setzt das zwar selbst beim ersten CTk(), aber der
    --autostart-Pfad laeuft ohne Settings-Fenster — daher explizit und frueh.
    """
    import ctypes
    try:
        # Windows 10 1703+: DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2.
        # Der Kontext-Handle ist pointer-gross — ohne argtypes wuerde -4 als
        # 32-Bit-int uebergeben und der Aufruf schluege auf x64 still fehl.
        user32 = ctypes.windll.user32
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def _clean_tmp_dir():
    """Loescht liegengebliebene Aufnahme-WAVs frueherer Sessions."""
    try:
        if not os.path.isdir(TMP_DIR):
            return
        for name in os.listdir(TMP_DIR):
            if name.startswith("vozii_rec_") and name.endswith(".wav"):
                try:
                    os.remove(os.path.join(TMP_DIR, name))
                except OSError:
                    pass
    except Exception:
        log.exception("Temp-Cleanup fehlgeschlagen")


def run():
    """Hauptschleife: Settings → Run → Fehler/Stop → zurueck zu Settings."""
    _enable_dpi_awareness()
    setup_logging()
    log.info("=" * 40)
    log.info("VoZii %s Start (PID %d)", __version__, os.getpid())

    set_language(load_config().get("ui_language", "de"))

    instance = acquire_single_instance()
    if instance == "busy":
        show_error(t("dialog.already_running.title"), t("dialog.already_running"))
        log.warning("Zweite Instanz blockiert")
        return
    if instance == "error":
        # Lock-Datei nicht anlegbar (read-only Ordner, AV) — kein Grund zu
        # sterben, nur der Doppelstart-Schutz fehlt dann
        log.warning("Single-Instance-Lock nicht verfuegbar — laufe ohne weiter")

    _clean_tmp_dir()

    if not check_vcredist():
        log.warning("VC++-Runtime fehlt (msvcp140/vcruntime140)")
        show_error(t("dialog.vcredist.title"), t("dialog.vcredist.body", url=VCREDIST_URL))

    # Autostart-Eintrag startet mit --autostart: direkt in den Tray-Betrieb,
    # ohne dass beim Boot das Settings-Fenster aufpoppt
    skip_settings = "--autostart" in sys.argv

    # Deterministische Fehler (z. B. kaputtes Audio-Subsystem) wuerden sonst
    # eine endlose Kette modaler Dialoge erzeugen
    crash_times = []

    while True:
        try:
            action = _run_cycle(skip_settings=skip_settings)
            skip_settings = False  # gilt nur fuer den ersten Zyklus
            if action == "quit":
                break
        except Exception as e:
            log.exception("_run_cycle crashed")
            now = time.monotonic()
            crash_times = [ts for ts in crash_times if now - ts < 60] + [now]
            if len(crash_times) >= 3:
                show_error(t("dialog.error.title"),
                           t("dialog.error.giveup", log_path=get_log_path()))
                break
            show_error(t("dialog.error.title"),
                       t("dialog.error.body", error=type(e).__name__,
                         log_path=get_log_path()))
            skip_settings = False
            continue

    log.info("VoZii beendet")
    # Tcl/Tk raeumt in der onefile-Exe beim Interpreter-Teardown unsauber auf
    # (tcl86t.dll-Crash, Event 1000). Hartes Prozess-Ende ist hier gefahrlos:
    # der whisper-server haengt am Kill-on-Close-Job, alle Zyklen sind beendet.
    logging.shutdown()
    os._exit(0)


def _run_cycle(skip_settings: bool = False) -> str:
    """Ein Zyklus: Settings zeigen → Tool laufen → 'quit' oder 'settings' zurueckgeben."""
    config = load_config()
    set_language(config.get("ui_language", "de"))

    gpu_type, gpu_name, from_cache = detect_gpu_cached(config)
    if config.get("gpu_type", "auto") != "auto":
        gpu_type = config["gpu_type"]
    backend_name = get_backend_name(gpu_type)

    log.info("GPU: %s (%s)%s", gpu_name or "CPU", backend_name,
             " [cache]" if from_cache else "")

    available_devices = AudioRecorder.list_input_devices()

    if skip_settings and is_setup_complete(config["model_size"]):
        log.info("Autostart: Settings uebersprungen, direkt in den Tray-Betrieb")
    else:
        settings = SettingsWindow(
            config=config,
            gpu_info=(gpu_type, gpu_name),
            backend_name=backend_name,
            available_devices=available_devices,
        )
        result = settings.run()

        if result is None:
            return "quit"

        config = result
        save_config(config)
        _set_auto_start(config.get("auto_start", False))

    # Audio device aufloesen — verschwundene Geraete (USB ab) -> Standard
    audio_device = None
    if config.get("audio_device"):
        for dev in available_devices:
            if dev["name"] == config["audio_device"]:
                audio_device = dev["index"]
                break
        if audio_device is None:
            log.warning("Konfiguriertes Mikrofon %r nicht gefunden — nutze Standard",
                        config["audio_device"])

    state = StateManager()
    recorder = AudioRecorder(device=audio_device)
    log.info("Mikrofon: %s", recorder.device_name)
    transcriber = Transcriber(
        model_size=config["model_size"],
        language=config["language"],
        performance_mode=config.get("performance_mode", "speed"),
        use_server=config.get("use_server", True),
    )
    text_processor = TextProcessor(
        mode=config.get("post_processing_mode", "off"),
        model=config.get("ollama_model", "llama3.2:3b"),
    )
    log.info("Post-processing: %s", text_processor.mode)
    history = TranscriptionHistory() if config.get("history_enabled", True) else None

    if not transcriber.is_ready():
        status = transcriber.get_status()
        log.error("Transcriber nicht bereit: %s", status)
        show_error(t("dialog.setup_missing.title"), t("dialog.setup_missing", status=status))
        return "settings"

    log.info("Transcriber: %s", transcriber.get_status())
    log.info("Hotkey: %s", config["hotkey"])

    audio_queue = queue.Queue()
    shutdown_event = threading.Event()
    return_to_settings = threading.Event()
    overlay = None
    hotkey_mgr = None

    # Ab hier laufen Hintergrundprozesse (whisper-server, Audio-Stream) —
    # das finally raeumt auch bei einem Crash auf, sonst leakt pro
    # Schleifendurchlauf ein Server (1,5 GB RAM beim Medium-Modell).
    try:
        # Server-Backend im Hintergrund vorwaermen (Modell laden), damit die
        # erste Transkription nicht darauf warten muss
        threading.Thread(target=transcriber.warmup, daemon=True).start()

        if config.get("show_overlay", True):
            overlay = RecordingOverlay()
            if overlay.start():
                state.on_change(overlay.update_state)
            else:
                overlay = None  # nicht mit totem Overlay weiterlaufen

        # Stream persistent oeffnen: eliminiert die Geraete-Open-Latenz beim
        # Hotkey-Druck. Schlaegt das fehl, versucht start_recording() es erneut.
        try:
            recorder.open_stream()
        except Exception:
            log.exception("Audio-Stream konnte nicht geoeffnet werden — "
                          "erneuter Versuch beim Aufnahmestart")

        use_sound = config.get("audio_feedback", True)

        def beep_start():
            if use_sound:
                threading.Thread(target=play_tone, args=(600, 80), daemon=True).start()

        def beep_done():
            if use_sound:
                threading.Thread(target=play_tone, args=(880, 60), daemon=True).start()

        def notify(code: str, duration_ms: int = 5000):
            """Kurzes visuelles Feedback (Status-Code im Overlay).

            Ohne Overlay waeren Fehler unsichtbar — dann wenigstens ein tiefer Ton."""
            if overlay:
                overlay.flash(code, duration_ms)
            elif code.startswith("err") and use_sound:
                threading.Thread(target=play_tone, args=(300, 250), daemon=True).start()

        def on_activate():
            try:
                if state.state == AppState.TRANSCRIBING:
                    return
                state.set_state(AppState.RECORDING)
                beep_start()
                recorder.start_recording()
                log.info("Aufnahme gestartet")
            except Exception:
                log.exception("on_activate fehlgeschlagen")
                state.set_state(AppState.IDLE)
                notify("err_mic")

        def on_deactivate():
            try:
                if state.state != AppState.RECORDING:
                    return
                wav_path, duration, rms = recorder.stop_recording()
                if wav_path:
                    state.set_state(AppState.TRANSCRIBING)
                    audio_queue.put((wav_path, duration, rms))
                else:
                    state.set_state(AppState.IDLE)
                    if duration > 0:
                        notify("short", 2000)
            except Exception:
                log.exception("on_deactivate fehlgeschlagen")
                state.set_state(AppState.IDLE)
                notify("err_mic")

        error_count = [0]
        hint_shown = [False]

        def transcription_worker():
            while not shutdown_event.is_set():
                try:
                    wav_path, duration, rms = audio_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                try:
                    text = transcriber.transcribe(wav_path)
                    if text and is_hallucination(text, duration, rms):
                        log.info("Halluzination verworfen (%.1fs, rms %.4f): %r",
                                 duration, rms, text)
                        text = ""
                    if text:
                        text = text_processor.process(text)
                    if text:
                        log.info("Transkribiert: %d Zeichen", len(text))
                        if history:
                            history.add(text)
                        inserted = insert_text(
                            text, restore_clipboard=config.get("restore_clipboard", True))
                        if inserted:
                            beep_done()
                        else:
                            # Text liegt in der Zwischenablage — Nutzer informieren
                            notify("clip")
                        error_count[0] = 0
                    else:
                        log.warning("Transkription leer")
                        # Erklaerbarer Backend-Fehler (SAC-Block, fehlende
                        # VC++-Runtime)? Einmal pro Zyklus als Dialog zeigen —
                        # sonst raetselt der Nutzer ueber leere Diktate.
                        hint = transcriber.last_error_hint
                        if hint and not hint_shown[0]:
                            hint_shown[0] = True
                            show_error(t("dialog.backend_blocked.title"), hint)
                        notify("empty", 2000)
                except Exception:
                    log.exception("Transkription fehlgeschlagen")
                    error_count[0] += 1
                    if error_count[0] >= 2:
                        notify("err_whisper")
                        error_count[0] = 0
                finally:
                    try:
                        os.remove(wav_path)
                    except OSError:
                        pass
                state.set_state(AppState.IDLE)

        def on_quit():
            # Nur das Shutdown-Signal setzen; das eigentliche Aufraeumen
            # (Server, Stream, Overlay, Hotkey) macht der finally-Block — egal
            # ueber welchen Pfad der Zyklus endet, genau einmal.
            shutdown_event.set()

        def on_open_settings():
            return_to_settings.set()
            on_quit()

        def on_open_log():
            try:
                os.startfile(get_log_path())
            except Exception:
                log.exception("Konnte Log nicht oeffnen")

        threading.Thread(target=transcription_worker, daemon=True).start()

        hotkey_mgr = HotkeyManager(
            hotkey_str=config["hotkey"],
            on_activate=on_activate,
            on_deactivate=on_deactivate,
            mode=config.get("mode", "push_to_talk"),
        )
        hotkey_mgr.start()

        def hotkey_watchdog():
            """Windows entfernt Low-Level-Hooks gelegentlich (Hook-Timeout) —
            dann waere der Hotkey bis zum App-Neustart tot. Alle 30s pruefen."""
            while not shutdown_event.wait(30):
                try:
                    if not hotkey_mgr.is_healthy():
                        log.warning("Hotkey-Listener tot — starte neu")
                        hotkey_mgr.restart()
                except Exception:
                    log.exception("Hotkey-Watchdog fehlgeschlagen")

        threading.Thread(target=hotkey_watchdog, daemon=True).start()

        tray = TrayApp(
            state, on_quit,
            hotkey_str=config["hotkey"],
            backend_name=backend_name,
            mic_name=recorder.device_name,
            on_open_settings=on_open_settings,
            on_open_log=on_open_log,
            history=history,
        )
        # First-Run: einmalig zeigen, wie es losgeht
        if overlay and not config.get("first_run_done", False):
            overlay.flash("ready", 6000, hotkey=config["hotkey"].upper())
            config["first_run_done"] = True
            save_config(config)

        log.info("VoZii laeuft")
        tray.run()
    finally:
        shutdown_event.set()
        if hotkey_mgr is not None:
            try:
                hotkey_mgr.stop()
            except Exception:
                log.exception("Hotkey-Stop fehlgeschlagen")
        transcriber.shutdown()
        recorder.close_stream()
        if overlay:
            overlay.stop()

    if return_to_settings.is_set():
        return "settings"
    return "quit"


def _set_auto_start(enabled: bool):
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        if enabled:
            # --autostart: beim Boot direkt in den Tray, kein Settings-Fenster
            if getattr(sys, "frozen", False):
                cmd = f'"{sys.executable}" --autostart'
            else:
                script = os.path.abspath(sys.argv[0])
                cmd = f'"{sys.executable}" "{script}" --autostart'
            winreg.SetValueEx(key, "VoZii", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, "VoZii")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception:
        log.exception("Autostart-Konfiguration fehlgeschlagen")
