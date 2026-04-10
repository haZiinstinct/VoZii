import logging
import os
import tempfile
import threading
import uuid

import numpy as np
import sounddevice as sd
from scipy.io import wavfile
from scipy.signal import resample_poly

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "float32"
MIN_DURATION = 0.3


class AudioRecorder:
    def __init__(self, device=None):
        self._buffer = []
        self._stream = None
        self._lock = threading.Lock()
        self._recording = False
        self._device = device
        self._session_id = uuid.uuid4().hex[:8]
        self._actual_rate = SAMPLE_RATE
        self._device_name = self._resolve_device_name()

    def _resolve_device_name(self) -> str:
        """Gibt einen lesbaren Namen des aktiven Devices zurueck."""
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

    def _try_open_stream(self, samplerate: int, use_auto_convert: bool) -> bool:
        """Versucht einen InputStream zu oeffnen. Returns True bei Erfolg."""
        extra = None
        if use_auto_convert:
            try:
                extra = sd.WasapiSettings(auto_convert=True)
            except Exception:
                extra = None

        try:
            self._stream = sd.InputStream(
                samplerate=samplerate,
                channels=CHANNELS,
                dtype=DTYPE,
                device=self._device,
                callback=self._callback,
                extra_settings=extra,
            )
            self._stream.start()
            self._actual_rate = samplerate
            return True
        except Exception as e:
            if self._stream:
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            return False

    def start_recording(self):
        with self._lock:
            self._buffer = []
            self._recording = True

            # Native Rate des Geraets ermitteln
            try:
                dev_info = (
                    sd.query_devices(self._device)
                    if self._device is not None
                    else sd.query_devices(kind="input")
                )
                native_rate = int(dev_info["default_samplerate"])
            except Exception:
                native_rate = 48000

            # Strategie 1: WASAPI auto_convert mit 16 kHz (beste Loesung)
            if self._try_open_stream(SAMPLE_RATE, use_auto_convert=True):
                log.info("Mikrofon '%s' @ %d Hz (WASAPI auto-convert)",
                         self._device_name, SAMPLE_RATE)
                return

            # Strategie 2: Fallback ohne auto_convert, verschiedene Raten
            # Bei nativer Rate: Aufnahme + manuelles Resample in stop_recording()
            candidates = []
            for r in (native_rate, 48000, 44100, SAMPLE_RATE):
                if r not in candidates:
                    candidates.append(r)

            for rate in candidates:
                if self._try_open_stream(rate, use_auto_convert=False):
                    if rate != SAMPLE_RATE:
                        log.info("Mikrofon '%s' @ %d Hz (wird zu %d Hz resampled)",
                                 self._device_name, rate, SAMPLE_RATE)
                    else:
                        log.info("Mikrofon '%s' @ %d Hz",
                                 self._device_name, rate)
                    return

            self._recording = False
            raise RuntimeError(
                f"Mikrofon '{self._device_name}' unterstuetzt keine nutzbare Sample-Rate. "
                f"Versuche Standard-Device in den Einstellungen."
            )

    def stop_recording(self) -> str | None:
        with self._lock:
            self._recording = False
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    log.exception("Fehler beim Schliessen des Audio-Streams")
                self._stream = None
            if not self._buffer:
                return None
            audio = np.concatenate(self._buffer, axis=0).flatten()
            self._buffer = []

        # Mindestlaenge basierend auf der tatsaechlichen Rate pruefen
        if len(audio) < self._actual_rate * MIN_DURATION:
            return None

        # Resample zu 16 kHz falls noetig (Whisper braucht zwingend 16 kHz)
        if self._actual_rate != SAMPLE_RATE:
            audio = resample_poly(audio, SAMPLE_RATE, self._actual_rate).astype(np.float32)

        audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
        tmp_path = os.path.join(
            tempfile.gettempdir(),
            f"vozii_rec_{os.getpid()}_{self._session_id}.wav",
        )
        wavfile.write(tmp_path, SAMPLE_RATE, audio_int16)
        return tmp_path

    @staticmethod
    def list_input_devices() -> list[dict]:
        """Nur WASAPI Input-Geraete — sauber, keine Duplikate."""
        devices = sd.query_devices()
        apis = sd.query_hostapis()

        wasapi_idx = None
        for i, api in enumerate(apis):
            if "WASAPI" in api["name"]:
                wasapi_idx = i
                break

        result = []
        skip = {"primary", "mapper", "default", "loopback"}

        for i, dev in enumerate(devices):
            if dev["max_input_channels"] <= 0:
                continue
            if wasapi_idx is not None and dev.get("hostapi") != wasapi_idx:
                continue
            name = dev["name"].strip()
            if any(s in name.lower() for s in skip):
                continue
            result.append({"index": i, "name": name})

        if not result:
            for i, dev in enumerate(devices):
                if dev["max_input_channels"] > 0:
                    result.append({"index": i, "name": dev["name"].strip()})

        return result
