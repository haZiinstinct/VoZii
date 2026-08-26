"""Audio: numpy-Resampling (Aliasing!), WAV-Schreiben, Halluzinations-Filter."""

import threading
import wave

import numpy as np

from src.audio import SAMPLE_RATE, AudioRecorder, _resample
from src.filters import is_hallucination


def _sine(freq: float, rate: int, duration: float) -> np.ndarray:
    t = np.arange(int(rate * duration)) / rate
    return np.sin(2 * np.pi * freq * t).astype(np.float32)


def _dominant_freq(signal: np.ndarray, rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(signal))
    freqs = np.fft.rfftfreq(len(signal), 1 / rate)
    return float(freqs[np.argmax(spectrum)])


def test_resample_48k_to_16k_keeps_frequency():
    sig = _sine(1000, 48000, 1.0)
    out = _resample(sig, 48000, 16000)
    assert len(out) == 16000
    assert abs(_dominant_freq(out, 16000) - 1000) < 10
    assert out.dtype == np.float32


def test_resample_44k1_to_16k_non_integer_ratio():
    sig = _sine(1000, 44100, 1.0)
    out = _resample(sig, 44100, 16000)
    assert abs(len(out) - 16000) <= 2
    assert abs(_dominant_freq(out, 16000) - 1000) < 10


def test_resample_suppresses_aliasing():
    """10 kHz liegt ueber der 16k-Nyquist (8 kHz) — ohne Tiefpass wuerde es
    als Alias bei 6 kHz erscheinen. Der Filter muss das stark daempfen."""
    sig = _sine(10000, 48000, 1.0)
    out = _resample(sig, 48000, 16000)
    spectrum = np.abs(np.fft.rfft(out))
    freqs = np.fft.rfftfreq(len(out), 1 / 16000)
    alias_energy = spectrum[(freqs > 5500) & (freqs < 6500)].max()
    total_input_energy = np.abs(np.fft.rfft(sig)).max()
    assert alias_energy < 0.05 * total_input_energy


def test_resample_noop_for_same_rate():
    sig = _sine(440, 16000, 0.5)
    out = _resample(sig, 16000, 16000)
    assert np.array_equal(out, sig)


def _recorder_with_buffer(samples: np.ndarray, rate: int) -> AudioRecorder:
    r = AudioRecorder.__new__(AudioRecorder)
    r._buffer = [samples.reshape(-1, 1)]
    r._stream = None
    r._lock = threading.Lock()
    r._recording = True
    r._closing = False
    r._stream_broken = False
    r._session_id = "test1234"
    r._actual_rate = rate
    return r


def test_stop_recording_writes_valid_wav(tmp_path, monkeypatch):
    import src.audio as audio_mod
    monkeypatch.setattr(audio_mod, "TMP_DIR", str(tmp_path))

    rec = _recorder_with_buffer(_sine(440, 16000, 1.0), 16000)
    wav_path, duration, rms = rec.stop_recording()

    assert wav_path is not None
    assert abs(duration - 1.0) < 0.01
    assert 0.6 < rms < 0.8  # Sinus mit Amplitude 1 -> rms ~0.707
    with wave.open(wav_path) as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == SAMPLE_RATE
        assert wf.getnframes() == 16000


def test_stop_recording_too_short_returns_none(tmp_path, monkeypatch):
    import src.audio as audio_mod
    monkeypatch.setattr(audio_mod, "TMP_DIR", str(tmp_path))

    rec = _recorder_with_buffer(_sine(440, 16000, 0.1), 16000)
    wav_path, duration, rms = rec.stop_recording()
    assert wav_path is None
    assert duration < 0.3


def test_stop_recording_empty_buffer():
    rec = _recorder_with_buffer(_sine(440, 16000, 1.0), 16000)
    rec._buffer = []
    assert rec.stop_recording() == (None, 0.0, 0.0)


# --- Halluzinations-Filter ---

def test_phantom_quiet_is_filtered():
    assert is_hallucination("Untertitelung des ZDF, 2020", 2.0, 0.001)
    assert is_hallucination("Vielen Dank.", 0.5, 0.02)
    assert is_hallucination("Thanks for watching!", 1.5, 0.002)
    assert is_hallucination("Untertitel der Amara.org-Community", 3.0, 0.001)


def test_normal_speech_loud_and_long_is_kept():
    assert not is_hallucination("Vielen Dank für die Blumen", 2.5, 0.05)
    assert not is_hallucination("Untertitelung des ZDF", 2.0, 0.05)  # laut + lang
    assert not is_hallucination("Schreib eine Mail an Thomas", 2.0, 0.002)


def test_quiet_but_not_phantom_is_kept():
    """Leise Sprecher duerfen nicht abgewuergt werden."""
    assert not is_hallucination("Termin morgen um drei", 1.5, 0.004)


def test_empty_text():
    assert not is_hallucination("", 0.5, 0.0)


# --- Auto-Stop bei Stille (M6) ---

def _recorder_for_autostop(timeout_s: float):
    import numpy as np  # noqa: F401
    from src.audio import AudioRecorder

    r = AudioRecorder.__new__(AudioRecorder)
    r._buffer = []
    r._recording = True
    r._actual_rate = 16000
    r._auto_stop_timeout = 0.0
    r._auto_stop_cb = None
    r._had_speech = False
    r._silence_frames = 0
    r._auto_stop_fired = False
    fired = []
    r.set_auto_stop(timeout_s, lambda: fired.append(1))
    return r, fired


def _feed(recorder, rms_level: float, seconds: float, block_s: float = 0.1):
    import numpy as np

    frames = int(16000 * block_s)
    block = np.full((frames, 1), rms_level, dtype=np.float32)
    for _ in range(int(seconds / block_s)):
        recorder._callback(block, frames, None, None)


def test_autostop_feuert_genau_einmal_nach_stille():
    r, fired = _recorder_for_autostop(2.0)
    _feed(r, 0.05, 1.0)    # Sprache
    _feed(r, 0.001, 1.9)   # Stille unter der Schwelle
    assert fired == []
    _feed(r, 0.001, 0.3)   # Schwelle ueberschritten
    assert fired == [1]
    _feed(r, 0.001, 5.0)   # bleibt bei genau einem Feuern
    assert fired == [1]


def test_autostop_feuert_nicht_bei_kurzer_sprechpause():
    r, fired = _recorder_for_autostop(2.0)
    _feed(r, 0.05, 1.0)
    _feed(r, 0.001, 1.5)   # Pause < 2s
    _feed(r, 0.05, 1.0)    # weitergesprochen -> Zaehler resettet
    _feed(r, 0.001, 1.5)
    assert fired == []


def test_autostop_feuert_nie_ohne_sprache():
    r, fired = _recorder_for_autostop(2.0)
    _feed(r, 0.001, 30.0)  # nur Stille — nie gesprochen
    assert fired == []


def test_autostop_aus_bei_timeout_null():
    r, fired = _recorder_for_autostop(0)
    _feed(r, 0.05, 1.0)
    _feed(r, 0.001, 30.0)
    assert fired == []


def test_autostop_flags_werden_pro_aufnahme_zurueckgesetzt():
    from src.audio import AudioRecorder

    r, fired = _recorder_for_autostop(2.0)
    _feed(r, 0.05, 0.5)
    _feed(r, 0.001, 2.5)
    assert fired == [1]

    # start_recording resettet die Flags (Stream-Teil gemockt)
    r._stream = type("S", (), {"active": True})()
    r._stream_broken = False
    import threading
    r._lock = threading.Lock()
    AudioRecorder.start_recording(r)
    assert r._had_speech is False and r._auto_stop_fired is False
    _feed(r, 0.05, 0.5)
    _feed(r, 0.001, 2.5)
    assert fired == [1, 1]
