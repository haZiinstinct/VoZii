"""Transcriber: Output-Cleaning, Flags, Multipart-Request, Server-Fallback."""

import http.server
import json
import threading

import pytest

from src import transcriber as transcriber_mod
from src.transcriber import (
    ServerBackend,
    Transcriber,
    _build_multipart,
    _clean_output,
    _quality_args,
    _threads,
    is_setup_complete,
)


def test_clean_output_removes_markers():
    assert _clean_output("[MUSIK] hallo  welt [BLANK_AUDIO]") == "hallo welt"
    assert _clean_output("  normaler   Satz. ") == "normaler Satz."
    assert _clean_output("") == ""
    assert _clean_output("[_BEG_]") == ""


def test_quality_args():
    assert _quality_args("speed") == {"beam_size": 1, "best_of": 1}
    assert _quality_args("quality") == {"beam_size": 5, "best_of": 5}
    # Unbekannter Wert -> schneller Default
    assert _quality_args("unsinn") == {"beam_size": 1, "best_of": 1}


def test_threads_in_sane_range():
    assert 2 <= _threads() <= 8


def test_build_multipart():
    body, content_type = _build_multipart(
        {"language": "de", "beam_size": "1"}, "file", "audio.wav", b"WAVDATA")
    boundary = content_type.split("boundary=")[1]
    assert boundary.encode() in body
    assert b'name="language"\r\n\r\nde' in body
    assert b'name="beam_size"\r\n\r\n1' in body
    assert b'filename="audio.wav"' in body
    assert b"WAVDATA" in body
    assert body.endswith(f"--{boundary}--\r\n".encode())


class _Handler(http.server.BaseHTTPRequestHandler):
    response_payload: dict = {}
    last_body: bytes = b""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        _Handler.last_body = self.rfile.read(length)
        data = json.dumps(_Handler.response_payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def _backend_on(port: int) -> ServerBackend:
    """ServerBackend ohne __init__ (kein Subprocess, kein atexit)."""
    b = ServerBackend.__new__(ServerBackend)
    b.language = "de"
    b.performance_mode = "speed"
    b._port = port
    b._proc = None
    return b


def test_server_request_parses_text(fake_server, tmp_path):
    _Handler.response_payload = {"text": "  hallo welt  "}
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF-fake-wav")
    backend = _backend_on(fake_server.server_address[1])

    assert backend._request(str(wav)) == "hallo welt"
    assert b"RIFF-fake-wav" in _Handler.last_body
    assert b'name="beam_size"\r\n\r\n1' in _Handler.last_body
    assert b'name="language"\r\n\r\nde' in _Handler.last_body


def test_server_request_raises_on_error_payload(fake_server, tmp_path):
    _Handler.response_payload = {"error": "failed to process audio"}
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    backend = _backend_on(fake_server.server_address[1])

    with pytest.raises(RuntimeError, match="failed to process"):
        backend._request(str(wav))


def test_facade_falls_back_to_cli(monkeypatch):
    class BoomServer:
        shutdowns = 0

        def transcribe(self, path):
            raise RuntimeError("server kaputt")

        def shutdown(self):
            BoomServer.shutdowns += 1

    class FakeCli:
        def transcribe(self, path):
            return "[MUSIK] hallo  vom  cli"

    t = Transcriber.__new__(Transcriber)
    t.model_size = "small"
    t.language = "de"
    t.model_path = "egal"
    t._server = BoomServer()
    t._cli = FakeCli()
    monkeypatch.setattr(Transcriber, "is_ready", lambda self: True)

    assert t.transcribe("x.wav") == "hallo vom cli"


def test_is_setup_complete_reine_dateipruefung(tmp_path, monkeypatch):
    """Darf KEIN Backend bauen (kein Job-Object/atexit) — war frueher ein Leak
    pro Autostart-Zyklus."""
    whisper_dir = tmp_path / "whisper-cpp"
    models_dir = whisper_dir / "models"
    models_dir.mkdir(parents=True)
    monkeypatch.setattr(transcriber_mod, "WHISPER_CLI", str(whisper_dir / "whisper-cli.exe"))
    monkeypatch.setattr(transcriber_mod, "MODELS_DIR", str(models_dir))

    job_calls = []
    monkeypatch.setattr(transcriber_mod, "create_kill_on_close_job",
                        lambda: job_calls.append(1))

    assert is_setup_complete("tiny") is False  # nichts vorhanden

    (whisper_dir / "whisper-cli.exe").write_bytes(b"MZ")
    model_file = models_dir / transcriber_mod.MODEL_FILES["tiny"]
    model_file.write_bytes(b"x")  # zu klein
    assert is_setup_complete("tiny") is False

    model_file.write_bytes(b"x" * transcriber_mod.MODEL_MIN_SIZES["tiny"])
    assert is_setup_complete("tiny") is True
    assert job_calls == []


def test_server_exit_code_hint_landet_in_exception(monkeypatch):
    """SAC-Block (0xC0E90002) muss als verstaendlicher Hinweis auftauchen."""
    hint = transcriber_mod._exit_code_hint(3236495362)
    assert "Smart App Control" in hint
    assert transcriber_mod._exit_code_hint(0) == ""


def test_facade_uses_server_result(monkeypatch):
    class OkServer:
        def transcribe(self, path):
            return " [_BEG_] text vom server "

    t = Transcriber.__new__(Transcriber)
    t.model_size = "small"
    t.language = "de"
    t.model_path = "egal"
    t._server = OkServer()
    t._cli = None  # darf nicht angefasst werden
    monkeypatch.setattr(Transcriber, "is_ready", lambda self: True)

    assert t.transcribe("x.wav") == "text vom server"
