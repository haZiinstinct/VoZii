import logging
import os
import queue
import sys
import threading
import traceback

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import __version__
from src.paths import TMP_DIR
from src.logger import setup_logging, acquire_single_instance, get_log_path
from src.state import AppState, StateManager
from src.config import load_config, save_config
from src.audio import AudioRecorder
from src.transcriber import Transcriber
from src.text_inserter import insert_text
from src.hotkey import HotkeyManager
from src.tray import TrayApp
from src.settings_gui import SettingsWindow
from src.hardware import detect_gpu_cached, get_backend_name
from src.overlay import RecordingOverlay
from src.text_processor import TextProcessor
from src.filters import is_hallucination
from src.history import TranscriptionHistory

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
        # Windows 10 1703+: DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except Exception:
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


def main():
    """Hauptschleife: Settings → Run → Fehler/Stop → zurueck zu Settings."""
    _enable_dpi_awareness()
    setup_logging()
    log.info("=" * 40)
    log.info("VoZii %s Start (PID %d)", __version__, os.getpid())

    if not acquire_single_instance():
        show_error("VoZii", "VoZii laeuft bereits.\n\nPruefe das Tray-Icon unten rechts.")
        log.warning("Zweite Instanz blockiert")
        return

    _clean_tmp_dir()

    # Autostart-Eintrag startet mit --autostart: direkt in den Tray-Betrieb,
    # ohne dass beim Boot das Settings-Fenster aufpoppt
    skip_settings = "--autostart" in sys.argv

    while True:
        try:
            action = _run_cycle(skip_settings=skip_settings)
            skip_settings = False  # gilt nur fuer den ersten Zyklus
            if action == "quit":
                break
        except Exception:
            log.exception("_run_cycle crashed")
            show_error("VoZii — Fehler", traceback.format_exc())
            skip_settings = False
            continue

    log.info("VoZii beendet")


def _setup_ready(config: dict) -> bool:
    """Sind Binary + Modell vorhanden (fuer den Settings-Skip beim Autostart)?"""
    return Transcriber(
        model_size=config["model_size"], language=config["language"],
    ).is_ready()


def _run_cycle(skip_settings: bool = False) -> str:
    """Ein Zyklus: Settings zeigen → Tool laufen → 'quit' oder 'settings' zurueckgeben."""
    config = load_config()

    gpu_type, gpu_name, from_cache = detect_gpu_cached(config)
    if config.get("gpu_type", "auto") != "auto":
        gpu_type = config["gpu_type"]
    backend_name = get_backend_name(gpu_type)

    log.info("GPU: %s (%s)%s", gpu_name or "CPU", backend_name,
             " [cache]" if from_cache else "")

    available_devices = AudioRecorder.list_input_devices()

    if skip_settings and _setup_ready(config):
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
        show_error("VoZii — Setup fehlt", f"{status}\n\nBitte Modell herunterladen.")
        return "settings"

    log.info("Transcriber: %s", transcriber.get_status())
    log.info("Hotkey: %s", config["hotkey"])

    # Server-Backend im Hintergrund vorwaermen (Modell laden), damit die
    # erste Transkription nicht darauf warten muss
    threading.Thread(target=transcriber.warmup, daemon=True).start()

    overlay = None
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

    audio_queue = queue.Queue()
    shutdown_event = threading.Event()
    return_to_settings = threading.Event()

    use_sound = config.get("audio_feedback", True)

    def beep_start():
        if use_sound:
            threading.Thread(target=play_tone, args=(600, 80), daemon=True).start()

    def beep_done():
        if use_sound:
            threading.Thread(target=play_tone, args=(880, 60), daemon=True).start()

    def notify(code: str, duration_ms: int = 5000):
        """Kurzes visuelles Feedback (Status-Code im Overlay)."""
        if overlay:
            overlay.flash(code, duration_ms)

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
            notify("ERR:MIC")

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
                    notify("SHORT", 2000)
        except Exception:
            log.exception("on_deactivate fehlgeschlagen")
            state.set_state(AppState.IDLE)
            notify("ERR:MIC")

    error_count = [0]

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
                        notify("CLIP")
                    error_count[0] = 0
                else:
                    log.warning("Transkription leer")
                    notify("LEER", 2000)
            except Exception:
                log.exception("Transkription fehlgeschlagen")
                error_count[0] += 1
                if error_count[0] >= 2:
                    notify("ERR:WHISPER")
                    error_count[0] = 0
            finally:
                try:
                    os.remove(wav_path)
                except OSError:
                    pass
            state.set_state(AppState.IDLE)

    def on_quit():
        shutdown_event.set()
        hotkey_mgr.stop()
        transcriber.shutdown()
        recorder.close_stream()
        if overlay:
            overlay.stop()

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
    log.info("VoZii laeuft")
    tray.run()

    shutdown_event.set()
    transcriber.shutdown()
    recorder.close_stream()

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


if __name__ == "__main__":
    main()
