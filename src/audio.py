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

# Raten die viele USB-Mikrofone unterstuetzen
FALLBACK_RATES = [SAMPLE_RATE, 48000, 44100, 32000, 22050, 16000]


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

    def _try_stream(self, device, samplerate: int) -> bool:
        """Versucht einen InputStream zu oeffnen. Returns True bei Erfolg."""
        try:
            self._stream = sd.InputStream(
                samplerate=samplerate,
                channels=CHANNELS,
                dtype=DTYPE,
                device=device,
                callback=self._callback,
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
        rates = []
        # Native Rate zuerst (funktioniert fast immer)
        if native not in rates:
            rates.append(native)
        for r in FALLBACK_RATES:
            if r not in rates:
                rates.append(r)

        for rate in rates:
            if self._try_stream(device, rate):
                return True
        return False

    def start_recording(self):
        with self._lock:
            self._buffer = []
            self._recording = True

            # Strategie 1: Gewaehltes Device
            if self._try_device(self._device):
                log.info("Mikrofon '%s' @ %d Hz%s",
                         self._device_name, self._actual_rate,
                         " (wird zu 16000 Hz resampled)" if self._actual_rate != SAMPLE_RATE else "")
                return

            # Strategie 2: Fallback auf Default-Device wenn spezifisches Device fehlschlaegt
            if self._device is not None:
                log.warning("Device '%s' nicht nutzbar, fallback auf Standard", self._device_name)
                if self._try_device(None):
                    try:
                        info = sd.query_devices(kind="input")
                        fallback_name = info["name"].strip()
                        log.info("Fallback Mikrofon '%s' @ %d Hz%s",
                                 fallback_name, self._actual_rate,
                                 " (wird zu 16000 Hz resampled)" if self._actual_rate != SAMPLE_RATE else "")
                    except Exception:
                        pass
                    return

            self._recording = False
            raise RuntimeError(
                f"Mikrofon '{self._device_name}' und Standard-Device liefern keine nutzbare Sample-Rate."
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

        if len(audio) < self._actual_rate * MIN_DURATION:
            return None

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
