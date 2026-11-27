import functools
import logging
import math
import os
import threading
import time
import uuid
import wave

import numpy as np
import sounddevice as sd

from src.filters import RMS_SILENCE_THRESHOLD
from src.i18n import t
from src.paths import TMP_DIR

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "float32"
MIN_DURATION = 0.3
# Sicherheitsgrenze gegen vergessene Toggle-Aufnahmen (~700 MB/h bei 48 kHz)
MAX_RECORDING_S = 600.0

# PortAudio ruft den Callback waehrend eines offenen Streams durchgehend auf
# (auch ohne laufende Aufnahme). Kommt laenger nichts, ist der Stream tot,
# ohne dass PortAudio das meldet: USB-Mikro kurz weg, Windows-Audio-Engine
# neu gestartet, Standby/Resume. `stream.active` bleibt dabei True — genau
# deshalb hat das Tool frueher still aufgehoert aufzunehmen.
STREAM_STALE_S = 5.0

# 16000 zuerst: DirectSound konvertiert die Rate selbst -> kein Resampling
# noetig. Danach gaengige native Raten als Fallback.
FALLBACK_RATES = [SAMPLE_RATE, 48000, 44100, 32000, 22050]


def compute_rms(audio: np.ndarray) -> float:
    """Allokationsfreier RMS ueber float32-Samples (kein temporaeres np.square)."""
    flat = audio.reshape(-1)
    if flat.size == 0:
        return 0.0
    return math.sqrt(float(np.dot(flat, flat)) / flat.size)


@functools.lru_cache(maxsize=16)
def _lowpass_kernel(src_rate: int, dst_rate: int) -> np.ndarray:
    """Gecachter float32-Windowed-Sinc-Tiefpass fuer _resample()."""
    cutoff = 0.45 * dst_rate / src_rate
    numtaps = 101
    t_idx = np.arange(numtaps, dtype=np.float64) - (numtaps - 1) / 2
    kernel = np.sinc(2 * cutoff * t_idx) * np.hamming(numtaps)
    kernel /= kernel.sum()
    return kernel.astype(np.float32)


def _resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Resampling in reinem numpy (ersetzt scipy.signal.resample_poly).

    Gecachter float32-Anti-Aliasing-Tiefpass + Polyphase-Dezimierung bei
    ganzzahligem Faktor (z. B. 48 -> 16 kHz: ~3x schneller, halber Speicher)
    bzw. lineare Interpolation. Fuer Sprache/Whisper voellig ausreichend.
    """
    audio_f32 = audio.astype(np.float32, copy=False)
    if src_rate == dst_rate or audio_f32.size == 0:
        return audio_f32

    kernel = _lowpass_kernel(src_rate, dst_rate)
    if src_rate % dst_rate == 0:
        step = src_rate // dst_rate
        half = (len(kernel) - 1) // 2
        padded = np.pad(audio_f32, half)
        windows = np.lib.stride_tricks.sliding_window_view(padded, len(kernel))[::step]
        return (windows @ kernel).astype(np.float32, copy=False)

    filtered = np.convolve(audio_f32, kernel, mode="same")
    n_out = int(len(filtered) * dst_rate / src_rate)
    x_new = np.linspace(0, len(filtered) - 1, n_out)
    return np.interp(x_new, np.arange(len(filtered)), filtered).astype(np.float32)


class AudioRecorder:
    """Persistenter Input-Stream: open_stream() einmal beim Run-Start,
    start/stop_recording() togglen nur das Aufnahme-Flag. Das eliminiert
    die Geraete-Open-Latenz beim Hotkey-Druck (abgeschnittene erste Silben).
    """

    def __init__(self, device=None):
        self._buffer = []
        self._stream = None
        self._lock = threading.Lock()
        self._recording = False
        self._closing = False
        self._stream_broken = False
        self._device = device
        self._session_id = uuid.uuid4().hex[:8]
        self._rec_seq = 0
        self._actual_rate = SAMPLE_RATE
        self._auto_stop_timeout = 0.0
        self._auto_stop_cb = None
        self._max_duration_s = MAX_RECORDING_S
        self._max_duration_cb = None
        self._max_duration_fired = False
        self._recorded_frames = 0
        self._had_speech = False
        self._silence_frames = 0
        self._auto_stop_fired = False
        self._last_callback = 0.0
        self._record_started = 0.0
        self._live_level = 0.0
        self._device_name = self._resolve_device_name()

    def _resolve_device_name(self) -> str:
        try:
            if self._device is None:
                info = sd.query_devices(kind="input")
                return f"{t('mic.default')} ({info['name'].strip()})"
            info = sd.query_devices(self._device)
            return info["name"].strip()
        except Exception:
            return t("mic.unknown")

    @property
    def device_name(self) -> str:
        return self._device_name

    @property
    def current_level(self) -> float:
        """Aktueller Mikrofonpegel (0.0..1.0) waehrend der Aufnahme fuers Overlay."""
        return self._live_level if self._recording else 0.0

    def set_auto_stop(self, timeout_s: float, callback):
        """Auto-Stop bei Stille (Toggle-Modus): callback feuert EINMAL pro
        Aufnahme aus dem PortAudio-Thread, sobald nach erkannter Sprache
        timeout_s Sekunden Stille vergangen sind. timeout_s <= 0 = aus.
        Feuert nie, bevor gesprochen wurde (leise Sprecher, Anlauf-Pausen)."""
        self._auto_stop_timeout = float(timeout_s or 0)
        self._auto_stop_cb = callback

    def set_max_duration(self, max_s: float, callback):
        """Sicherheits-Stopp bei sehr langen (vergessenen) Aufnahmen."""
        self._max_duration_s = float(max_s or 0)
        self._max_duration_cb = callback

    def _callback(self, indata, frames, time_info, status):
        # Herzschlag zuerst — er muss auch ausserhalb einer Aufnahme ticken,
        # sonst faende der Watchdog einen gesunden Stream nie wieder gesund
        self._last_callback = time.monotonic()
        if not self._recording:
            return
        self._buffer.append(indata.copy())
        rms = compute_rms(indata)
        # 0.125 RMS ~ Vollausschlag fuer die Overlay-Pegelanzeige
        self._live_level = min(1.0, rms * 8.0)

        # Sicherheitsgrenze gegen unbegrenzten RAM-Verbrauch (vergessener Toggle)
        max_cb = getattr(self, "_max_duration_cb", None)
        max_s = getattr(self, "_max_duration_s", 0.0)
        if max_cb is not None and max_s > 0 and not getattr(self, "_max_duration_fired", False):
            self._recorded_frames = getattr(self, "_recorded_frames", 0) + frames
            if self._recorded_frames / self._actual_rate >= max_s:
                self._max_duration_fired = True
                log.warning("Maximale Aufnahmedauer (%.0fs) erreicht — stoppe automatisch", max_s)
                try:
                    max_cb()
                except Exception:
                    log.exception("Max-Duration-Callback fehlgeschlagen")
                return

        if (self._auto_stop_timeout <= 0 or self._auto_stop_cb is None
                or self._auto_stop_fired):
            return
        # Stille-Dauer aus Frames akkumulieren (nicht Wallclock — PortAudio
        # liefert Bloecke nicht in Echtzeit-Garantie)
        if rms >= RMS_SILENCE_THRESHOLD:
            self._had_speech = True
            self._silence_frames = 0
        elif self._had_speech:
            self._silence_frames += frames
            if self._silence_frames / self._actual_rate >= self._auto_stop_timeout:
                self._auto_stop_fired = True
                try:
                    self._auto_stop_cb()
                except Exception:
                    log.exception("Auto-Stop-Callback fehlgeschlagen")

    def _on_stream_finished(self):
        """PortAudio meldet Stream-Ende — unerwartet heisst: Geraet weg oder
        Standby/Resume. Beim naechsten Aufnahmestart wird neu geoeffnet."""
        if not self._closing:
            log.warning("Audio-Stream unerwartet beendet (Geraet getrennt/Standby?)")
            self._stream_broken = True

    def _try_stream(self, device, samplerate: int) -> bool:
        """Versucht einen InputStream zu oeffnen. Returns True bei Erfolg."""
        try:
            self._stream = sd.InputStream(
                samplerate=samplerate,
                channels=CHANNELS,
                dtype=DTYPE,
                device=device,
                callback=self._callback,
                finished_callback=self._on_stream_finished,
            )
            self._stream.start()
            self._actual_rate = samplerate
            self._last_callback = time.monotonic()
            return True
        except Exception:
            if self._stream:
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            return False

    def _get_native_rate(self, device) -> int:
        try:
            if device is None:
                info = sd.query_devices(kind="input")
            else:
                info = sd.query_devices(device)
            return int(info["default_samplerate"])
        except Exception:
            return 48000

    def _try_device(self, device) -> bool:
        """Versucht alle Raten fuer ein bestimmtes Device durchzugehen."""
        native = self._get_native_rate(device)
        rates = list(FALLBACK_RATES)
        if native not in rates:
            rates.insert(1, native)  # nach 16000, vor den uebrigen Fallbacks

        for rate in rates:
            if self._try_stream(device, rate):
                return True
        return False

    def open_stream(self):
        """Oeffnet den Stream und haelt ihn offen. Raised RuntimeError wenn
        weder das gewaehlte noch das Standard-Device funktioniert."""
        with self._lock:
            self._open_stream_locked()

    def is_stream_healthy(self) -> bool:
        """Liefert der Stream noch Audio? Basis fuer Watchdog und Aufnahmestart."""
        with self._lock:
            return self._is_stream_healthy_locked()

    def _is_stream_healthy_locked(self) -> bool:
        if self._stream is None or self._stream_broken:
            return False
        if not getattr(self._stream, "active", False):
            return False
        return (time.monotonic() - self._last_callback) < STREAM_STALE_S

    def ensure_stream(self) -> bool:
        """Oeffnet den Stream neu, falls er stumm geworden ist.

        Returns True, wenn danach ein gesunder Stream steht. Wird vom
        Watchdog gerufen, damit ein toter Stream nicht bis zum naechsten
        App-Neustart tot bleibt.
        """
        with self._lock:
            if self._is_stream_healthy_locked():
                return True
            if self._recording:
                # Mitten in einer Aufnahme neu oeffnen wuerde das bereits
                # aufgenommene Material verlieren — das uebernimmt der
                # naechste start_recording()
                return False
            log.warning("Audio-Stream liefert nichts mehr — oeffne neu")
            try:
                self._open_stream_locked()
                return True
            except Exception:
                log.exception("Audio-Stream konnte nicht neu geoeffnet werden")
                return False

    def _open_stream_locked(self):
        self._close_stream_locked()
        self._stream_broken = False

        # Strategie 1: Gewaehltes Device
        if self._try_device(self._device):
            log.info("Mikrofon '%s' @ %d Hz%s",
                     self._device_name, self._actual_rate,
                     " (wird zu 16000 Hz resampled)" if self._actual_rate != SAMPLE_RATE else "")
            return

        # Strategie 2: Fallback auf Default-Device
        if self._device is not None:
            log.warning("Device '%s' nicht nutzbar, fallback auf Standard", self._device_name)
            if self._try_device(None):
                try:
                    info = sd.query_devices(kind="input")
                    log.info("Fallback Mikrofon '%s' @ %d Hz", info["name"].strip(), self._actual_rate)
                except Exception:
                    pass
                return

        raise RuntimeError(
            f"Mikrofon '{self._device_name}' und Standard-Device liefern keine nutzbare Sample-Rate."
        )

    def start_recording(self):
        with self._lock:
            if not self._is_stream_healthy_locked():
                log.info("Audio-Stream nicht aktiv — oeffne neu")
                self._open_stream_locked()
            self._buffer = []
            self._had_speech = False
            self._silence_frames = 0
            self._auto_stop_fired = False
            self._recorded_frames = 0
            self._max_duration_fired = False
            self._live_level = 0.0
            self._record_started = time.monotonic()
            self._recording = True

    def snapshot(self, max_s: float = 0) -> tuple[np.ndarray | None, float]:
        """Aktueller Aufnahmestand fuer die Live-Vorschau, ohne die Aufnahme
        anzuhalten. Returns (audio 16 kHz float32, gesamte Dauer in s).

        max_s > 0 liefert nur die letzten max_s Sekunden — die Vorschau
        zeigt ohnehin nur das Ende, so bleibt die Rechenzeit pro Durchlauf
        auch bei langen Diktaten konstant."""
        with self._lock:
            if not self._recording or not self._buffer:
                return None, 0.0
            # Flache Kopie der Liste reicht: die Bloecke selbst werden nie
            # veraendert, der Callback haengt nur neue an
            buffer = list(self._buffer)
            rate = self._actual_rate
        total = sum(len(b) for b in buffer) / rate
        need = int(max_s * rate) if max_s > 0 else 0
        if need:
            tail, n = [], 0
            for block in reversed(buffer):
                tail.append(block)
                n += len(block)
                if n >= need:
                    break
            buffer = tail[::-1]
        audio = np.concatenate(buffer, axis=0).reshape(-1)
        if need:
            audio = audio[-need:]
        if rate != SAMPLE_RATE:
            audio = _resample(audio, rate, SAMPLE_RATE)
        return audio.astype(np.float32, copy=False), total

    def stop_recording_pcm(self) -> tuple[np.ndarray | None, float, float]:
        """Beendet die Aufnahme ohne Festplatten-I/O.

        Returns (audio_16k_float32, dauer_s, rms); audio ist None bei leerer
        oder zu kurzer Aufnahme. Der Stream bleibt offen (persistent) —
        close_stream() schliesst ihn am Zyklusende bzw. im Bluetooth-Leerlauf.
        """
        with self._lock:
            self._recording = False
            self._live_level = 0.0
            buffer, self._buffer = self._buffer, []
            rate = self._actual_rate
            held_s = time.monotonic() - self._record_started

        if not buffer:
            # Laenger gedrueckt und trotzdem kein einziger Block: der Stream
            # ist stumm geworden, ohne dass PortAudio das gemeldet hat.
            # Markieren, damit die naechste Aufnahme ihn neu oeffnet.
            if held_s >= MIN_DURATION:
                log.warning("Aufnahme ueber %.1fs ohne Audiodaten — Stream wird "
                            "neu geoeffnet", held_s)
                self._stream_broken = True
            return None, 0.0, 0.0

        audio = np.concatenate(buffer, axis=0).reshape(-1)
        duration = len(audio) / rate
        if duration < MIN_DURATION:
            return None, duration, 0.0

        # RMS auf den float32-Rohdaten — Grundlage fuer den Halluzinations-Filter
        rms = compute_rms(audio)

        if rate != SAMPLE_RATE:
            audio = _resample(audio, rate, SAMPLE_RATE)

        return audio.astype(np.float32, copy=False), duration, rms

    def stop_recording(self) -> tuple[str | None, float, float]:
        """Beendet die Aufnahme und schreibt ein 16-kHz-WAV. Returns (wav_path, dauer_s, rms)."""
        audio, duration, rms = self.stop_recording_pcm()
        if audio is None:
            return None, duration, rms

        audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
        os.makedirs(TMP_DIR, exist_ok=True)
        self._rec_seq = getattr(self, "_rec_seq", 0) + 1
        tmp_path = os.path.join(
            TMP_DIR,
            f"vozii_rec_{os.getpid()}_{self._session_id}_{self._rec_seq}.wav",
        )
        with wave.open(tmp_path, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_int16.tobytes())
        return tmp_path, duration, rms

    def close_stream(self):
        with self._lock:
            self._recording = False
            self._close_stream_locked()

    def _close_stream_locked(self):
        if self._stream is None:
            return
        self._closing = True
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            log.exception("Fehler beim Schliessen des Audio-Streams")
        finally:
            self._stream = None
            self._closing = False

    @staticmethod
    def list_input_devices() -> list[dict]:
        """Input Devices mit Bevorzugung von DirectSound (robusteste Rate-Konvertierung).

        Reihenfolge:
        1. DirectSound (voller Name, immer Rate-Konvertierung)
        2. MME (Fallback, Namen auf 32 Zeichen begrenzt)
        3. WASAPI (als letztes, strenge Rate-Regeln)
        """
        devices = sd.query_devices()
        apis = sd.query_hostapis()

        # Host API indices nach Bevorzugung
        preferred_apis = []
        for api_name in ("DirectSound", "MME", "WASAPI"):
            for i, api in enumerate(apis):
                if api_name in api["name"]:
                    preferred_apis.append(i)
                    break

        skip = {"primary", "prim", "mapper", "default", "loopback", "soundmapper",
                "soundaufnahmetreiber"}
        seen_names = set()
        result = []

        # Iteriere ueber Host APIs in Praeferenz-Reihenfolge
        for api_idx in preferred_apis:
            for i, dev in enumerate(devices):
                if dev["max_input_channels"] <= 0:
                    continue
                if dev.get("hostapi") != api_idx:
                    continue
                name = dev["name"].strip()
                lower = name.lower()
                if any(s in lower for s in skip):
                    continue
                # Dedup per vollem Namen (inkl. Klammer-Inhalt) — sonst verlieren
                # wir verschiedene Devices die alle "Microphone (...)" heissen
                if lower in seen_names:
                    continue
                seen_names.add(lower)
                result.append({"index": i, "name": name})

        # Fallback: wenn nichts gefunden, zeige ALLE input devices
        if not result:
            for i, dev in enumerate(devices):
                if dev["max_input_channels"] > 0:
                    result.append({"index": i, "name": dev["name"].strip()})

        return result
