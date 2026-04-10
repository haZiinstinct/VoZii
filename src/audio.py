import os
import tempfile
import threading

import numpy as np
import sounddevice as sd
from scipy.io import wavfile

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

    def _callback(self, indata, frames, time_info, status):
        if self._recording:
            self._buffer.append(indata.copy())

    def start_recording(self):
        with self._lock:
            self._buffer = []
            self._recording = True
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                device=self._device,
                callback=self._callback,
            )
            self._stream.start()

    def stop_recording(self) -> str | None:
        with self._lock:
            self._recording = False
            if self._stream:
                self._stream.stop()
                self._stream.close()
                self._stream = None
            if not self._buffer:
                return None
            audio = np.concatenate(self._buffer, axis=0).flatten()
            self._buffer = []

        if len(audio) < SAMPLE_RATE * MIN_DURATION:
            return None

        audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
        tmp_path = os.path.join(tempfile.gettempdir(), "vozii_recording.wav")
        wavfile.write(tmp_path, SAMPLE_RATE, audio_int16)
        return tmp_path

    @staticmethod
    def list_input_devices() -> list[dict]:
        """Nur WASAPI Input-Geraete — sauber, keine Duplikate."""
        devices = sd.query_devices()
        apis = sd.query_hostapis()

        # Find WASAPI API index
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
            # Only WASAPI devices (if available)
            if wasapi_idx is not None and dev.get("hostapi") != wasapi_idx:
                continue
            name = dev["name"].strip()
            if any(s in name.lower() for s in skip):
                continue
            result.append({"index": i, "name": name})

        # Fallback: if WASAPI filter returned nothing, show all
        if not result:
            for i, dev in enumerate(devices):
                if dev["max_input_channels"] > 0:
                    result.append({"index": i, "name": dev["name"].strip()})

        return result
