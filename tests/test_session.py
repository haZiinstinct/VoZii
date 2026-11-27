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
    assert s.overlay.flashes == ["err_whisper"]  # sofort melden, nicht still schlucken


def test_worker_ueberspringt_totstille():
    calls = []

    class CountingTranscriber(FakeTranscriber):
        def transcribe(self, audio):
            calls.append(audio)
            return "phantom"

    s, inserted = _session(transcriber=CountingTranscriber())
    s.process(np.zeros(16000, dtype=np.float32), 1.0, 0.0)
    assert calls == []
    assert inserted == []
    assert s.overlay.flashes == ["empty"]
    assert s.state.state == AppState.IDLE


def test_on_activate_ignoriert_doppelstart_waehrend_recording():
    rec = FakeRecorder()
    s, _ = _session(recorder=rec)
    s.on_activate()
    s.on_activate()
    assert rec.started == 1


def test_release_mic_idle_schliesst_stream_nach_pause():
    closed = []

    class ClosableRecorder(FakeRecorder):
        def close_stream(self):
            closed.append(True)
            self.healthy = False

    class FakeMgr:
        def is_healthy(self):
            return True

        def release_if_stuck(self):
            return False

    rec = ClosableRecorder()
    s, _ = _session(config={"release_mic_idle": True}, recorder=rec)
    s.hotkey_mgr = FakeMgr()
    s._last_used -= session_mod.MIC_IDLE_CLOSE_S + 5
    s.health_check()
    assert closed == [True]
    assert rec.ensured == 0  # im Bluetooth-Modus nicht sofort wieder oeffnen


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


# --- Leerlauf-Entladen ---

class LazyTranscriber(FakeTranscriber):
    def __init__(self):
        super().__init__()
        self.loaded = True
        self.released = 0
        self.prepared = 0

    def release(self):
        self.released += 1
        self.loaded = False
        return True

    def prepare_async(self):
        self.prepared += 1


def test_entlaedt_erst_nach_leerlaufzeit():
    tr = LazyTranscriber()
    s, _ = _session(config={"idle_unload_min": 10}, transcriber=tr)
    t0 = s._last_used
    assert s.release_if_idle(now=t0 + 599) is False
    # 601 statt 600: (t0 + 600) - t0 ergibt je nach t0 durch Gleitkomma-
    # Rundung knapp unter 600 — der Test schlug dann sporadisch fehl
    assert s.release_if_idle(now=t0 + 601) is True
    assert tr.released == 1
    # Schon entladen -> kein zweites release()
    assert s.release_if_idle(now=t0 + 1200) is False
    assert tr.released == 1


def test_entlaedt_nicht_waehrend_aufnahme_oder_wenn_aus():
    tr = LazyTranscriber()
    s, _ = _session(config={"idle_unload_min": 10}, transcriber=tr)
    s.state.set_state(AppState.RECORDING)
    assert s.release_if_idle(now=s._last_used + 10_000) is False

    tr2 = LazyTranscriber()
    s2, _ = _session(config={"idle_unload_min": 0}, transcriber=tr2)
    assert s2.release_if_idle(now=s2._last_used + 10_000) is False
    assert tr2.released == 0


def test_hotkey_laedt_modell_im_sparmodus_vor():
    tr = LazyTranscriber()
    s, _ = _session(config={"idle_unload_min": 10}, transcriber=tr)
    s.on_activate()
    assert tr.prepared == 1

    tr2 = LazyTranscriber()
    s2, _ = _session(config={"idle_unload_min": 0}, transcriber=tr2)
    s2.on_activate()
    assert tr2.prepared == 0  # Modell ist dauerhaft geladen, nichts zu tun


def test_transkription_setzt_leerlauf_zurueck(tmp_path):
    tr = LazyTranscriber()
    s, _ = _session(config={"idle_unload_min": 10}, transcriber=tr)
    s._last_used = 0.0
    s.process(str(_wav(tmp_path)), 2.0, 0.1)
    assert s._last_used > 0.0


# --- Live-Vorschau ---

import numpy as np  # noqa: E402

from src import session as session_mod  # noqa: E402


class LiveRecorder(FakeRecorder):
    def __init__(self, audio, total):
        super().__init__()
        self.audio, self.total = audio, total

    def snapshot(self, max_s=0):
        return self.audio, self.total


class LiveTranscriber(FakeTranscriber):
    live_capable = True

    def __init__(self, preview_text="hallo welt"):
        super().__init__()
        self.preview_text = preview_text
        self.previews = 0

    def preview(self, audio):
        self.previews += 1
        return self.preview_text


class LiveOverlay(FakeOverlay):
    def __init__(self):
        super().__init__()
        self.previews = []

    def preview(self, text):
        self.previews.append(text)


def _speech(seconds):
    return (0.1 * np.ones(int(16000 * seconds))).astype(np.float32)


def _live_session(audio, total, config=None, text="hallo welt"):
    s, _ = _session(config, recorder=LiveRecorder(audio, total),
                    transcriber=LiveTranscriber(text))
    s.overlay = LiveOverlay()
    s.state.set_state(AppState.RECORDING)
    return s


def test_live_step_zeigt_vorschau():
    s = _live_session(_speech(2), 2.0)
    assert s.live_step(0.0) == 2.0
    assert s.overlay.previews == ["hallo welt"]


def test_live_step_ueberspringt_stille_und_kurze_aufnahmen():
    s = _live_session(np.zeros(32000, dtype=np.float32), 2.0)
    assert s.live_step(0.0) == 0.0
    s = _live_session(_speech(0.5), 0.5)
    assert s.live_step(0.0) == 0.0
    assert s.transcriber.previews == 0


def test_live_step_ohne_neues_audio_rechnet_nicht():
    s = _live_session(_speech(2), 2.0)
    assert s.live_step(1.9) == 1.9
    assert s.transcriber.previews == 0


def test_live_step_schneidet_erstes_wort_bei_vollem_fenster():
    s = _live_session(_speech(session_mod.LIVE_WINDOW_S), 30.0, text="abgeschnit tenes Wort")
    s.live_step(0.0)
    assert s.overlay.previews == ["… tenes Wort"]


def test_live_step_nicht_mehr_nach_aufnahmeende():
    s = _live_session(_speech(2), 2.0)
    s.state.set_state(AppState.TRANSCRIBING)
    s.live_step(0.0)
    assert s.overlay.previews == []


def test_live_vorschau_abschaltbar():
    s = _live_session(_speech(2), 2.0, config={"live_preview": False})
    s.state.set_state(AppState.IDLE)
    s.on_activate()
    assert s._live_stop is None
    s.on_deactivate()


def test_live_vorschau_nur_wenn_engine_schnell_genug():
    s = _live_session(_speech(2), 2.0)
    s.transcriber.live_capable = False
    s.state.set_state(AppState.IDLE)
    s.on_activate()
    assert s._live_stop is None


def test_live_thread_startet_und_stoppt_mit_aufnahme():
    s = _live_session(_speech(2), 2.0)
    s.state.set_state(AppState.IDLE)
    s.on_activate()
    stop = s._live_stop
    assert stop is not None and not stop.is_set()
    s.on_deactivate()
    assert stop.is_set() and s._live_stop is None


def test_live_step_rechnet_nicht_in_sprechpause():
    # 3 s Sprache, dann 5 s Stille: der Pegel ueber das ganze Fenster liegt
    # ueber der Schwelle, das Fensterende ist aber still
    audio = np.concatenate([_speech(3), np.zeros(16000 * 5, dtype=np.float32)])
    s = _live_session(audio, 8.0)
    assert s.live_step(0.0) == 0.0
    assert s.transcriber.previews == 0


def test_live_loop_endet_mit_zyklusende(monkeypatch):
    monkeypatch.setattr(session_mod, "LIVE_INTERVAL_S", 0.01)
    s = _live_session(_speech(2), 2.0)
    s.shutdown_event.set()
    s._live_loop(threading.Event())  # kehrt zurueck, obwohl stop nie gesetzt wird
    assert s.transcriber.previews == 0
