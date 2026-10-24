"""Parakeet-Engine: Chunking, Backend, Multi-File-Download, Facade-Routing,
GPU->CPU-Fallback."""

import os
import wave

import numpy as np
import pytest

from src import downloader, parakeet
from src import transcriber as transcriber_mod
from src.parakeet import ParakeetBackend, split_chunks, supports_language
from src.transcriber import CliBackend, Transcriber, is_setup_complete

SR = 16000


def _write_wav(path, audio: np.ndarray):
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())


def _tone(seconds: float, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


# --- Sprachen ---

def test_supports_language():
    assert supports_language("auto")
    assert supports_language("de")
    assert supports_language("uk")
    assert not supports_language("ja")
    assert not supports_language("zh")


# --- Chunking ---

def test_split_chunks_kurz_bleibt_ganz():
    audio = _tone(10)
    chunks = split_chunks(audio)
    assert len(chunks) == 1 and len(chunks[0]) == len(audio)


def test_split_chunks_schneidet_in_der_pause():
    # 40 s Ton, 1 s Stille, 20 s Ton -> Schnitt muss in der Stille liegen
    audio = np.concatenate([_tone(40), np.zeros(SR, dtype=np.float32), _tone(20)])
    chunks = split_chunks(audio, max_s=45)
    assert sum(len(c) for c in chunks) == len(audio)
    assert len(chunks) == 2
    assert 40 * SR <= len(chunks[0]) <= 41 * SR


def test_split_chunks_ohne_pause_hart_an_der_grenze():
    audio = _tone(100)
    chunks = split_chunks(audio, max_s=45)
    assert sum(len(c) for c in chunks) == len(audio)
    assert [len(c) for c in chunks[:2]] == [45 * SR, 45 * SR]
    assert all(len(c) <= 45 * SR for c in chunks)


# --- Backend (Modell gemockt) ---

class FakeModel:
    def __init__(self):
        self.calls = []

    def recognize(self, audio):
        self.calls.append(len(audio))
        return f" teil{len(self.calls)} "


def test_backend_fuegt_bloecke_zusammen(tmp_path, monkeypatch):
    wav = tmp_path / "a.wav"
    _write_wav(wav, _tone(100))
    model = FakeModel()
    backend = ParakeetBackend(threads=2)
    monkeypatch.setattr(backend, "_load", lambda: model)

    assert backend.transcribe(str(wav)) == "teil1 teil2 teil3"
    assert len(model.calls) == 3
    assert backend.last_error_hint == ""


def test_backend_ladefehler_setzt_hinweis(tmp_path, monkeypatch):
    wav = tmp_path / "a.wav"
    _write_wav(wav, _tone(1))
    backend = ParakeetBackend(threads=2)

    def boom():
        raise RuntimeError("onnx kaputt")

    monkeypatch.setattr(backend, "_load", boom)
    with pytest.raises(RuntimeError):
        backend.transcribe(str(wav))
    assert "onnx kaputt" in backend.last_error_hint


def test_read_wav_lehnt_falsche_rate_ab(tmp_path):
    wav = tmp_path / "a.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(b"\x00\x00" * 100)
    with pytest.raises(ValueError):
        parakeet._read_wav(str(wav))


# --- Multi-File-Download ---

@pytest.fixture
def parakeet_files(tmp_path, monkeypatch):
    """Zwei kleine Fake-Dateien statt der echten 650 MB."""
    import hashlib

    files = {"a.onnx": b"AAAA" * 10, "vocab.txt": b"hallo"}
    pins = {n: (hashlib.sha256(d).hexdigest(), len(d)) for n, d in files.items()}
    d = tmp_path / "parakeet"
    monkeypatch.setattr(downloader, "PARAKEET_DIR", str(d))
    monkeypatch.setattr(downloader, "PARAKEET_FILES", pins)
    return d, files


def test_parakeet_installiert_nur_bei_exakter_groesse(parakeet_files):
    d, files = parakeet_files
    assert not downloader.is_model_installed(downloader.PARAKEET_MODEL)
    d.mkdir()
    for name, data in files.items():
        (d / name).write_bytes(data)
    assert downloader.is_model_installed(downloader.PARAKEET_MODEL)
    (d / "vocab.txt").write_bytes(b"hal")
    assert not downloader.is_model_installed(downloader.PARAKEET_MODEL)


def test_parakeet_download_summiert_fortschritt(parakeet_files, monkeypatch):
    d, files = parakeet_files
    d.mkdir()
    (d / "vocab.txt").write_bytes(files["vocab.txt"])  # schon da -> nicht neu laden
    loaded, progress = [], []

    def fake_download(url, dest, cb=None, expected_sha256=None):
        name = os.path.basename(dest)
        loaded.append(name)
        data = files[name]
        cb(len(data), len(data), 0)
        with open(dest, "wb") as f:
            f.write(data)

    monkeypatch.setattr(downloader, "download_file", fake_download)
    assert downloader.download_model(downloader.PARAKEET_MODEL,
                                     lambda dl, total, speed: progress.append((dl, total)))
    assert loaded == ["a.onnx"]
    total = sum(len(v) for v in files.values())
    assert progress[-1] == (total, total)


def test_is_setup_complete_parakeet_ohne_whisper_cli(parakeet_files, monkeypatch, tmp_path):
    d, files = parakeet_files
    monkeypatch.setattr(transcriber_mod, "WHISPER_CLI", str(tmp_path / "fehlt.exe"))
    assert not is_setup_complete(downloader.PARAKEET_MODEL)
    d.mkdir()
    for name, data in files.items():
        (d / name).write_bytes(data)
    assert is_setup_complete(downloader.PARAKEET_MODEL)


# --- Facade ---

class FakeParakeet:
    def __init__(self, text="parakeet text", fail=False):
        self.text, self.fail = text, fail
        self.last_error_hint = ""

    def transcribe(self, path):
        if self.fail:
            raise RuntimeError("kaputt")
        return self.text


class FakeCli:
    def __init__(self, results):
        self.results = list(results)  # (text, returncode)
        self.no_gpu = False
        self.last_returncode = None
        self.last_error_hint = ""
        self.calls = []

    def transcribe(self, path):
        text, self.last_returncode = self.results.pop(0)
        self.calls.append(self.no_gpu)
        return text


def _facade(engine="whisper", parakeet_backend=None, cli=None, whisper_ok=True):
    t = Transcriber.__new__(Transcriber)
    t.model_size = downloader.PARAKEET_MODEL if engine == "parakeet" else "small"
    t.whisper_model = "small"
    t.language = "de"
    t.model_path = "egal"
    t.engine = engine
    t._parakeet = parakeet_backend
    t._server = None
    t._cli = cli
    t._whisper_ok = whisper_ok
    return t


def test_facade_parakeet_engine():
    t = _facade("parakeet", FakeParakeet("  Hallo  Welt. "), cli=None)
    assert t.transcribe("x.wav") == "Hallo Welt."


def test_facade_parakeet_fehler_faellt_auf_whisper(monkeypatch):
    monkeypatch.setattr(Transcriber, "_gpu_backend", staticmethod(lambda: False))
    cli = FakeCli([("vom whisper", 0)])
    t = _facade("parakeet", FakeParakeet(fail=True), cli=cli)
    assert t.transcribe("x.wav") == "vom whisper"


def test_facade_parakeet_fehler_ohne_whisper_wirft():
    t = _facade("parakeet", FakeParakeet(fail=True), cli=None, whisper_ok=False)
    with pytest.raises(RuntimeError):
        t.transcribe("x.wav")


def test_gpu_crash_wechselt_auf_cpu_whisper(monkeypatch):
    monkeypatch.setattr(Transcriber, "_gpu_backend", staticmethod(lambda: True))
    cli = FakeCli([("", 0xC0000005), ("text auf cpu", 0)])
    t = _facade("whisper", None, cli=cli)
    assert t.transcribe("x.wav") == "text auf cpu"
    assert cli.calls == [False, True]  # zweiter Versuch mit -ng
    assert t.pop_notice() == "cpu_fallback"
    assert t.pop_notice() == ""


def test_gpu_crash_bevorzugt_parakeet(monkeypatch):
    monkeypatch.setattr(Transcriber, "_gpu_backend", staticmethod(lambda: True))
    cli = FakeCli([("", 0xC0000409)])
    t = _facade("whisper", FakeParakeet("vom parakeet"), cli=cli)
    assert t.transcribe("x.wav") == "vom parakeet"
    assert t.engine == "parakeet"


def test_sac_block_kein_cpu_wechsel(monkeypatch):
    """Smart App Control trifft die CPU genauso — Wechsel bringt nichts."""
    monkeypatch.setattr(Transcriber, "_gpu_backend", staticmethod(lambda: True))
    cli = FakeCli([("", 0xC0E90002)])
    t = _facade("whisper", None, cli=cli)
    assert t.transcribe("x.wav") == ""
    assert cli.calls == [False]
    assert t.pop_notice() == ""


def test_leeres_diktat_auf_cpu_kein_wechsel(monkeypatch):
    monkeypatch.setattr(Transcriber, "_gpu_backend", staticmethod(lambda: False))
    cli = FakeCli([("", 0)])
    t = _facade("whisper", None, cli=cli)
    assert t.transcribe("x.wav") == ""
    assert cli.calls == [False]


def test_cli_no_gpu_flag(monkeypatch):
    captured = {}

    class FakeResult:
        returncode = 0
        stdout = "text"
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeResult()

    monkeypatch.setattr(transcriber_mod.subprocess, "run", fake_run)
    cli = CliBackend("m.bin", "de", "speed")
    cli.transcribe("a.wav")
    assert "-ng" not in captured["cmd"]
    cli.no_gpu = True
    cli.transcribe("a.wav")
    assert "-ng" in captured["cmd"]


# --- Engine-Wahl im Konstruktor ---

def test_konstruktor_routet_fremdsprache_zu_whisper(monkeypatch):
    monkeypatch.setattr(transcriber_mod, "is_model_installed", lambda m: True)
    monkeypatch.setattr(transcriber_mod, "is_server_available", lambda: False)
    monkeypatch.setattr(Transcriber, "_gpu_backend", staticmethod(lambda: False))

    t = Transcriber(model_size=downloader.PARAKEET_MODEL, language="de",
                    whisper_model="small")
    assert t.engine == "parakeet"
    t = Transcriber(model_size=downloader.PARAKEET_MODEL, language="ja",
                    whisper_model="small")
    assert t.engine == "whisper"
    assert t.whisper_model == "small"


def test_config_akzeptiert_parakeet(config_paths):
    import yaml

    from src.config import load_config

    config_path, _ = config_paths
    config_path.write_text(yaml.dump({"model_size": "parakeet-v3-int8",
                                      "whisper_model": "parakeet-v3-int8"}))
    cfg = load_config()
    assert cfg["model_size"] == "parakeet-v3-int8"
    # whisper_model darf nur ein Whisper-Modell sein
    assert cfg["whisper_model"] == "large-v3-turbo-q5_0"
