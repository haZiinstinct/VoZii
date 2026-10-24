"""Parakeet-Backend — NVIDIA Parakeet TDT 0.6B v3 (int8) in-process via onnx-asr.

Die schnelle CPU-Engine fuer normale Laptops: ~20-35x Echtzeit auf der CPU,
setzt Satzzeichen/Grossschreibung selbst, erkennt die Sprache automatisch
(25 europaeische Sprachen). Kein Subprozess, kein Server — das Modell bleibt
nach dem ersten Laden im RAM (~1 GB).
"""

import logging
import threading
import wave

import numpy as np

from src.downloader import PARAKEET_DIR
from src.filters import RMS_SILENCE_THRESHOLD
from src.i18n import t

log = logging.getLogger(__name__)

# Sprachen, die Parakeet v3 kann. Alles andere (zh, ja, ar, ...) -> Whisper.
PARAKEET_LANGS = frozenset({
    "bg", "cs", "da", "de", "el", "en", "es", "et", "fi", "fr", "hr", "hu", "it",
    "lt", "lv", "mt", "nl", "pl", "pt", "ro", "ru", "sk", "sl", "sv", "uk",
})

_SAMPLE_RATE = 16000
# Lange Diktate in Bloecke schneiden: Attention-Speicher waechst quadratisch,
# Bloecke halten RAM und Latenz auf Laptops im Rahmen.
_MAX_CHUNK_S = 45
# Schnitt an der leisesten Stelle in den letzten Sekunden vor der Blockgrenze
_CUT_SEARCH_S = 10
_CUT_WINDOW_S = 0.1


def supports_language(language: str) -> bool:
    """'auto' zaehlt als unterstuetzt — Parakeet erkennt die Sprache selbst."""
    return language == "auto" or language in PARAKEET_LANGS


def _read_wav(wav_path: str) -> np.ndarray:
    """16-Bit-PCM-WAV (wie von audio.py geschrieben) -> float32 mono -1..1."""
    with wave.open(wav_path, "rb") as wf:
        if wf.getsampwidth() != 2 or wf.getframerate() != _SAMPLE_RATE:
            raise ValueError(f"Unerwartetes WAV-Format: {wf.getsampwidth() * 8} Bit, "
                             f"{wf.getframerate()} Hz")
        frames = wf.readframes(wf.getnframes())
        channels = wf.getnchannels()
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio


def split_chunks(audio: np.ndarray, max_s: float = _MAX_CHUNK_S) -> list[np.ndarray]:
    """Teilt lange Aufnahmen an Sprechpausen in Bloecke <= max_s.

    Gesucht wird das leiseste 100-ms-Fenster in den letzten _CUT_SEARCH_S
    vor der Grenze; ist es nicht still, wird hart an der Grenze geschnitten."""
    max_len = int(max_s * _SAMPLE_RATE)
    if len(audio) <= max_len:
        return [audio]
    win = int(_CUT_WINDOW_S * _SAMPLE_RATE)
    search = int(min(_CUT_SEARCH_S, max_s / 2) * _SAMPLE_RATE)
    chunks = []
    start = 0
    while len(audio) - start > max_len:
        region = audio[start + max_len - search:start + max_len]
        n = len(region) // win
        rms = np.sqrt(np.mean(region[:n * win].reshape(n, win) ** 2, axis=1))
        best = int(np.argmin(rms))
        if rms[best] < RMS_SILENCE_THRESHOLD:
            cut = start + max_len - search + best * win + win // 2
        else:
            cut = start + max_len
        chunks.append(audio[start:cut])
        start = cut
    chunks.append(audio[start:])
    return chunks


class ParakeetBackend:
    """In-process-Transkription; gleiches Interface wie CliBackend/ServerBackend."""

    def __init__(self, threads: int, model_dir: str = PARAKEET_DIR):
        self.model_dir = model_dir
        self.threads = threads
        self.last_error_hint = ""
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        # Import erst hier: onnxruntime kostet ~0,5 s Startzeit und wird von
        # reinen Whisper-Nutzern nie gebraucht
        import onnx_asr
        import onnxruntime as rt

        opts = rt.SessionOptions()
        opts.intra_op_num_threads = self.threads
        opts.inter_op_num_threads = 1
        log.info("Lade Parakeet (%d Threads, %s)", self.threads, self.model_dir)
        model = onnx_asr.load_model(
            "nemo-parakeet-tdt-0.6b-v3", self.model_dir, quantization="int8",
            sess_options=opts, providers=["CPUExecutionProvider"])
        log.info("Parakeet bereit")
        return model

    def ensure_loaded(self):
        with self._lock:
            if self._model is not None:
                return
            try:
                self._model = self._load()
            except Exception as e:
                self.last_error_hint = t("err.hint.parakeet", error=e)
                raise

    def warmup(self):
        """Laedt das Modell und rechnet einmal Stille durch — die erste
        ONNX-Inferenz ist deutlich langsamer als alle folgenden."""
        self.ensure_loaded()
        with self._lock:
            self._model.recognize(np.zeros(_SAMPLE_RATE, dtype=np.float32))

    def transcribe(self, wav_path: str) -> str:
        self.ensure_loaded()
        audio = _read_wav(wav_path)
        parts = []
        try:
            with self._lock:
                for chunk in split_chunks(audio):
                    text = self._model.recognize(chunk)
                    if text and text.strip():
                        parts.append(text.strip())
        except Exception as e:
            self.last_error_hint = t("err.hint.parakeet", error=e)
            raise
        self.last_error_hint = ""
        return " ".join(parts)

    def shutdown(self):
        with self._lock:
            self._model = None
