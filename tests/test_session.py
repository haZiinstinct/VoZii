"""RunSession: Zusammenspiel Hotkey <-> Recorder <-> Worker (vorher app._run_cycle)."""

import threading

from src.hotkey import HotkeyManager
from src.session import RunSession
from src.state import AppState, StateManager
from src.transcriber import TranscriptionTimeout


class FakeRecorder:
    def __init__(self, result=("x.wav", 2.0, 0.1), healthy=True):
        self.result = result
        self.healthy = healthy
        self.started = 0
        self.ensured = 0
        self.auto_stop = None

    def start_recording(self):
        self.started += 1

    def stop_recording(self):
        return self.result

    def is_stream_healthy(self):
        return self.healthy

    def ensure_stream(self):
        self.ensured += 1

    def set_auto_stop(self, seconds, callback):
        self.auto_stop = (seconds, callback)


class FakeTranscriber:
    def __init__(self, text="hallo welt", exc=None, hint=""):
        self.text = text
        self.exc = exc
        self.last_error_hint = hint

    def transcribe(self, path):
        if self.exc:
            raise self.exc
        return self.text


class FakeProcessor:
    def process(self, text):
        return text


class FakeOverlay:
    def __init__(self):
        self.flashes = []

    def flash(self, code, duration_ms=5000):
        self.flashes.append(code)


def _session(config=None, **kw):
    inserted = []
    kw.setdefault("recorder", FakeRecorder())
    kw.setdefault("transcriber", FakeTranscriber())
    s = RunSession(
        config={"audio_feedback": False, **(config or {})},
        state=StateManager(),
        text_processor=FakeProcessor(),
        overlay=FakeOverlay(),
        insert=lambda text, restore_clipboard=True: inserted.append(text) or True,
        **kw,
    )
    return s, inserted


def _wav(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    return wav


# --- Hotkey-Callbacks ---

def test_aufnahme_landet_in_der_queue():
    s, _ = _session()
    s.on_activate()
    assert s.state.state == AppState.RECORDING
    s.on_deactivate()
    assert s.state.state == AppState.TRANSCRIBING
    assert s.audio_queue.get_nowait() == ("x.wav", 2.0, 0.1)


def test_leere_aufnahme_bei_totem_stream_meldet_err_mic():
    rec = FakeRecorder(result=(None, 0, 0.0), healthy=False)
    s, _ = _session(recorder=rec)
    s.on_activate()
    s.on_deactivate()
    assert s.state.state == AppState.IDLE
    assert s.overlay.flashes == ["err_mic"]
    assert rec.ensured == 1


def test_zu_kurze_aufnahme_meldet_short():
    s, _ = _session(recorder=FakeRecorder(result=(None, 0.3, 0.1)))
    s.on_activate()
    s.on_deactivate()
    assert s.overlay.flashes == ["short"]


def test_kein_neustart_waehrend_transkription():
    rec = FakeRecorder()
    s, _ = _session(recorder=rec)
    s.state.set_state(AppState.TRANSCRIBING)
    s.on_activate()
    assert rec.started == 0


def test_auto_stop_naechster_druck_startet_sofort():
    """Auto-Stop im Umschalt-Modus laeuft ueber den HotkeyManager — der
    naechste Druck muss eine neue Aufnahme starten, nicht erst 'Aus' holen."""
    rec = FakeRecorder()
    s, _ = _session(config={"mode": "toggle", "auto_stop_silence_s": 3.0}, recorder=rec)
    s.install_auto_stop()
    mgr = HotkeyManager("f9", on_activate=s.on_activate, on_deactivate=s.on_deactivate,
                        mode="toggle")
    mgr._fire = lambda cb: cb()  # synchron statt Dispatcher-Thread
    s.hotkey_mgr = mgr

    mgr._handle_press("f9")
    mgr._handle_release("f9")
    assert s.state.state == AppState.RECORDING

    seconds, callback = rec.auto_stop
    assert seconds == 3.0
    callback()  # Stille erkannt
    assert s.state.state == AppState.TRANSCRIBING
    s.audio_queue.get_nowait()
    s.state.set_state(AppState.IDLE)  # Worker fertig

    mgr._handle_press("f9")
    mgr._handle_release("f9")
    assert s.state.state == AppState.RECORDING
    assert rec.started == 2


def test_auto_stop_nur_im_umschalt_modus():
    rec = FakeRecorder()
    s, _ = _session(config={"mode": "push_to_talk", "auto_stop_silence_s": 3.0}, recorder=rec)
    s.install_auto_stop()
    assert rec.auto_stop is None


# --- Worker ---

def test_worker_fuegt_text_ein_und_loescht_wav(tmp_path):
    wav = _wav(tmp_path)
    history = []

    class FakeHistory:
        def add(self, text):
            history.append(text)

    s, inserted = _session(history=FakeHistory())
    s.state.set_state(AppState.TRANSCRIBING)
    s.process(str(wav), 2.0, 0.1)
    assert inserted == ["hallo welt"]
    assert history == ["hallo welt"]
    assert not wav.exists()
    assert s.state.state == AppState.IDLE


def test_worker_loescht_wav_auch_bei_exception(tmp_path):
    wav = _wav(tmp_path)
    s, inserted = _session(transcriber=FakeTranscriber(exc=RuntimeError("kaputt")))
    s.process(str(wav), 2.0, 0.1)
    assert not wav.exists()
    assert inserted == []
    assert s.state.state == AppState.IDLE
    assert s.overlay.flashes == []  # erst ab dem zweiten Fehler in Folge
    s.process(str(_wav(tmp_path)), 2.0, 0.1)
    assert s.overlay.flashes == ["err_whisper"]


def test_worker_timeout_meldet_too_long(tmp_path):
    s, _ = _session(transcriber=FakeTranscriber(exc=TranscriptionTimeout("t")))
    s.process(str(_wav(tmp_path)), 120.0, 0.1)
    assert s.overlay.flashes == ["too_long"]
    assert s.state.state == AppState.IDLE


def test_leeres_ergebnis_zeigt_hinweis_nur_einmal(tmp_path):
    dialogs = []
    s, _ = _session(transcriber=FakeTranscriber(text="", hint="Smart App Control"),
                    show_error=lambda title, msg: dialogs.append(msg))
    s.process(str(_wav(tmp_path)), 2.0, 0.1)
    s.process(str(_wav(tmp_path)), 2.0, 0.1)
    assert dialogs == ["Smart App Control"]
    assert s.overlay.flashes == ["empty", "empty"]


def test_einfuegen_fehlgeschlagen_meldet_clip(tmp_path):
    s, _ = _session()
    s._insert = lambda text, restore_clipboard=True: False
    s.process(str(_wav(tmp_path)), 2.0, 0.1)
    assert s.overlay.flashes == ["clip"]


def test_worker_thread_endet_mit_shutdown(tmp_path):
    s, inserted = _session()
    worker = threading.Thread(target=s.transcription_worker, daemon=True)
    worker.start()
    s.audio_queue.put((str(_wav(tmp_path)), 2.0, 0.1))
    for _ in range(100):
        if inserted:
            break
        threading.Event().wait(0.02)
    s.shutdown_event.set()
    worker.join(timeout=2)
    assert inserted == ["hallo welt"]
    assert not worker.is_alive()


# --- Watchdog / Feedback ---

def test_health_check_startet_toten_hotkey_neu_und_heilt_stream():
    calls = []

    class FakeMgr:
        def is_healthy(self):
            return False

        def restart(self):
            calls.append("restart")

    rec = FakeRecorder()
    s, _ = _session(recorder=rec)
    s.hotkey_mgr = FakeMgr()
    s.health_check()
    assert calls == ["restart"]
    assert rec.ensured == 1

    s.state.set_state(AppState.RECORDING)  # waehrend der Aufnahme Stream nicht anfassen
    s.health_check()
    assert rec.ensured == 1


def test_ohne_overlay_fehlerton():
    tones = []
    s, _ = _session(config={"audio_feedback": True},
                    play_tone=lambda f, ms: tones.append(f))
    s.overlay = None
    s._tone = lambda f, ms: tones.append(f)  # synchron statt Thread
    s.notify("err_mic")
    s.notify("short")
    assert tones == [300]
