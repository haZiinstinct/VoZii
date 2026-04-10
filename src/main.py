import os
import sys
import queue
import threading
import traceback

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.paths import BASE_DIR
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


def show_error(title: str, msg: str):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, msg)
        root.destroy()
    except Exception:
        print(f"[FEHLER] {title}: {msg}")


def play_tone(freq: int, duration_ms: int):
    """Spielt einen angenehmeren Ton (niedrigere Frequenz, kuerzer)."""
    try:
        import winsound
        winsound.Beep(freq, duration_ms)
    except Exception:
        pass


def main():
    """Hauptschleife: Settings → Run → Fehler/Stop → zurueck zu Settings."""
    while True:
        try:
            action = _run_cycle()
            if action == "quit":
                break
            # action == "settings" → loop continues, zeigt Settings erneut
        except Exception:
            show_error("VoZii — Fehler", traceback.format_exc())
            # Nach Fehler: zurueck zu Settings statt Absturz
            continue

    print("[OK] VoZii beendet.")


def _run_cycle() -> str:
    """Ein Zyklus: Settings zeigen → Tool laufen → 'quit' oder 'settings' zurueckgeben."""
    config = load_config()

    # Hardware erkennen
    gpu_type, gpu_name = detect_gpu()
    if config.get("gpu_type", "auto") != "auto":
        gpu_type = config["gpu_type"]
    backend_name = get_backend_name(gpu_type)

    print(f"[OK] GPU: {gpu_name or 'CPU'} ({backend_name})")

    available_devices = AudioRecorder.list_input_devices()

    # Settings-Fenster anzeigen
    settings = SettingsWindow(
        config=config,
        gpu_info=(gpu_type, gpu_name),
        backend_name=backend_name,
        available_devices=available_devices,
    )
    result = settings.run()

    if result is None:
        return "quit"  # User hat geschlossen

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
        show_error(
            "VoZii — Setup fehlt",
            f"{transcriber.get_status()}\n\nBitte Modell herunterladen.",
        )
        return "settings"  # Zurueck zu Settings

    print(f"[OK] {transcriber.get_status()}")
    print(f"[OK] Hotkey: {config['hotkey']}")

    # Overlay
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

    def on_activate():
        if state.state == AppState.TRANSCRIBING:
            return
        state.set_state(AppState.RECORDING)
        beep_start()
        recorder.start_recording()
        print("[REC] Aufnahme...")

    def on_deactivate():
        if state.state != AppState.RECORDING:
            return
        wav_path = recorder.stop_recording()
        if wav_path:
            state.set_state(AppState.TRANSCRIBING)
            print(f"[REC] Gespeichert: {wav_path}")
            audio_queue.put(wav_path)
        else:
            print("[REC] Zu kurz, ignoriert.")
            state.set_state(AppState.IDLE)

    def transcription_worker():
        while not shutdown_event.is_set():
            try:
                wav_path = audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                text = transcriber.transcribe(wav_path)
                if text:
                    print(f"[TEXT] {text}")
                    insert_text(text, restore_clipboard=config.get("restore_clipboard", True))
                    beep_done()
            except Exception as e:
                print(f"[FEHLER] {e}")
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
        """Tray: Einstellungen → Stop + zurueck zu Settings."""
        return_to_settings.set()
        on_quit()

    # Worker starten
    threading.Thread(target=transcription_worker, daemon=True).start()

    # Hotkey starten
    hotkey_mgr = HotkeyManager(
        hotkey_str=config["hotkey"],
        on_activate=on_activate,
        on_deactivate=on_deactivate,
        mode=config.get("mode", "push_to_talk"),
    )
    hotkey_mgr.start()

    # Tray starten (blockiert)
    tray = TrayApp(
        state, on_quit,
        hotkey_str=config["hotkey"],
        backend_name=backend_name,
        on_open_settings=on_open_settings,
    )
    print("[OK] VoZii laeuft.")
    tray.run()

    shutdown_event.set()

    if return_to_settings.is_set():
        return "settings"  # Zurueck zu Settings
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
        pass


if __name__ == "__main__":
    main()
