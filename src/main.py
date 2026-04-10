import logging
import os
import queue
import sys
import threading
import traceback

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.paths import BASE_DIR
from src.logger import setup_logging, acquire_single_instance, get_log_path
from src.state import AppState, StateManager
from src.config import load_config, save_config
from src.audio import AudioRecorder
from src.transcriber import Transcriber
from src.text_inserter import insert_text
from src.hotkey import HotkeyManager
from src.tray import TrayApp
from src.settings_gui import SettingsWindow
from src.hardware import detect_gpu, get_backend_name
from src.overlay import RecordingOverlay

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


def main():
    """Hauptschleife: Settings → Run → Fehler/Stop → zurueck zu Settings."""
    setup_logging()
    log.info("=" * 40)
    log.info("VoZii Start (PID %d)", os.getpid())

    if not acquire_single_instance():
        show_error("VoZii", "VoZii laeuft bereits.\n\nPruefe das Tray-Icon unten rechts.")
        log.warning("Zweite Instanz blockiert")
        return

    while True:
        try:
            action = _run_cycle()
            if action == "quit":
                break
        except Exception:
            log.exception("_run_cycle crashed")
            show_error("VoZii — Fehler", traceback.format_exc())
            continue

    log.info("VoZii beendet")


def _run_cycle() -> str:
    """Ein Zyklus: Settings zeigen → Tool laufen → 'quit' oder 'settings' zurueckgeben."""
    config = load_config()

    gpu_type, gpu_name = detect_gpu()
    if config.get("gpu_type", "auto") != "auto":
        gpu_type = config["gpu_type"]
    backend_name = get_backend_name(gpu_type)

    log.info("GPU: %s (%s)", gpu_name or "CPU", backend_name)

    available_devices = AudioRecorder.list_input_devices()

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

    # Audio device aufloesen
    audio_device = None
    if config.get("audio_device"):
        for dev in available_devices:
            if dev["name"] == config["audio_device"]:
                audio_device = dev["index"]
                break

    state = StateManager()
    recorder = AudioRecorder(device=audio_device)
    transcriber = Transcriber(
        model_size=config["model_size"],
        language=config["language"],
    )

    if not transcriber.is_ready():
        status = transcriber.get_status()
        log.error("Transcriber nicht bereit: %s", status)
        show_error("VoZii — Setup fehlt", f"{status}\n\nBitte Modell herunterladen.")
        return "settings"

    log.info("Transcriber: %s", transcriber.get_status())
    log.info("Hotkey: %s", config["hotkey"])

    overlay = None
    if config.get("show_overlay", True):
        overlay = RecordingOverlay()
        overlay.start()
        state.on_change(overlay.update_state)

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

    def notify_error(msg: str):
        """Kurzes visuelles Feedback fuer Fehler."""
        if overlay:
            overlay.flash_error(msg)

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
            notify_error("Aufnahme-Start fehlgeschlagen")

    def on_deactivate():
        try:
            if state.state != AppState.RECORDING:
                return
            wav_path = recorder.stop_recording()
            if wav_path:
                state.set_state(AppState.TRANSCRIBING)
                audio_queue.put(wav_path)
            else:
                state.set_state(AppState.IDLE)
        except Exception:
            log.exception("on_deactivate fehlgeschlagen")
            state.set_state(AppState.IDLE)
            notify_error("Aufnahme-Stopp fehlgeschlagen")

    error_count = [0]

    def transcription_worker():
        while not shutdown_event.is_set():
            try:
                wav_path = audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                text = transcriber.transcribe(wav_path)
                if text:
                    log.info("Transkribiert: %d Zeichen", len(text))
                    insert_text(text, restore_clipboard=config.get("restore_clipboard", True))
                    beep_done()
                    error_count[0] = 0
                else:
                    log.warning("Transkription leer")
            except Exception:
                log.exception("Transkription fehlgeschlagen")
                error_count[0] += 1
                if error_count[0] >= 2:
                    notify_error("Transkription fehlgeschlagen")
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

    tray = TrayApp(
        state, on_quit,
        hotkey_str=config["hotkey"],
        backend_name=backend_name,
        on_open_settings=on_open_settings,
        on_open_log=on_open_log,
    )
    log.info("VoZii laeuft")
    tray.run()

    shutdown_event.set()

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
            winreg.SetValueEx(key, "VoZii", 0, winreg.REG_SZ, f'"{sys.executable}"')
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
