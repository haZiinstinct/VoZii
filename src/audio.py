import logging
import os
import threading
import uuid
import wave

import numpy as np
import sounddevice as sd

from src.paths import TMP_DIR

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "float32"
MIN_DURATION = 0.3

# 16000 zuerst: DirectSound konvertiert die Rate selbst -> kein Resampling
# noetig. Danach gaengige native Raten als Fallback.
FALLBACK_RATES = [SAMPLE_RATE, 48000, 44100, 32000, 22050]


def _resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Resampling in reinem numpy (ersetzt scipy.signal.resample_poly).

    Anti-Aliasing-Tiefpass (windowed sinc) + Decimation bzw. lineare
    Interpolation. Fuer Sprache/Whisper voellig ausreichend.
    """
    if src_rate == dst_rate:
        return audio.astype(np.float32)

    # Tiefpass bei 90 % der Ziel-Nyquist-Frequenz (normiert auf src_rate)
    cutoff = 0.45 * dst_rate / src_rate
    numtaps = 101
    t = np.arange(numtaps) - (numtaps - 1) / 2
    kernel = np.sinc(2 * cutoff * t) * np.hamming(numtaps)
    kernel /= kernel.sum()
    filtered = np.convolve(audio, kernel, mode="same")

    if src_rate % dst_rate == 0:
        return filtered[:: src_rate // dst_rate].astype(np.float32)

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
        self._actual_rate = SAMPLE_RATE
        self._device_name = self._resolve_device_name()

    def _resolve_device_name(self) -> str:
        try:
            if self._device is None:
                info = sd.query_devices(kind="input")
                return f"Standard ({info['name'].strip()})"
            info = sd.query_devices(self._device)
            return info["name"].strip()
        except Exception:
            return "Unbekannt"

    @property
    def device_name(self) -> str:
        return self._device_name

    def _callback(self, indata, frames, time_info, status):
        if self._recording:
            self._buffer.append(indata.copy())

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
            stream_dead = (
                self._stream is None
                or self._stream_broken
                or not getattr(self._stream, "active", False)
            )
            if stream_dead:
                log.info("Audio-Stream nicht aktiv — oeffne neu")
                self._open_stream_locked()
            self._buffer = []
            self._recording = True

    def stop_recording(self) -> tuple[str | None, float, float]:
        """Beendet die Aufnahme. Returns (wav_path, dauer_s, rms).

        wav_path ist None bei leerer/zu kurzer Aufnahme. Der Stream bleibt
        offen (persistent) — close_stream() schliesst ihn am Zyklusende.
        """
        with self._lock:
            self._recording = False
            buffer, self._buffer = self._buffer, []
            rate = self._actual_rate

        if not buffer:
            return None, 0.0, 0.0

        audio = np.concatenate(buffer, axis=0).flatten()
        duration = len(audio) / rate
        if duration < MIN_DURATION:
            return None, duration, 0.0

        # RMS auf den float32-Rohdaten — Grundlage fuer den Halluzinations-Filter
        rms = float(np.sqrt(np.mean(np.square(audio))))

        if rate != SAMPLE_RATE:
            audio = _resample(audio, rate, SAMPLE_RATE)

        audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
        os.makedirs(TMP_DIR, exist_ok=True)
        tmp_path = os.path.join(
            TMP_DIR,
            f"vozii_rec_{os.getpid()}_{self._session_id}.wav",
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
