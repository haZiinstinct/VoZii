"""Transkription via whisper.cpp — persistenter Server-Modus mit CLI-Fallback.

ServerBackend haelt das Modell im RAM (whisper-server.exe, nur 127.0.0.1):
spart das Neu-Laden des Modells (75 MB - 1,5 GB) bei jeder Transkription.
CliBackend ist der robuste Fallback (whisper-cli.exe pro Aufruf).
"""

import atexit
import io
import json
import logging
import os
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid

from src.downloader import MODEL_FILES, MODEL_MIN_SIZES, is_server_available
from src.errors import VCREDIST_URL, classify_win_exit_code
from src.i18n import t
from src.paths import BASE_DIR
from src.winutil import assign_process_to_job, create_kill_on_close_job

log = logging.getLogger(__name__)

WHISPER_DIR = os.path.join(BASE_DIR, "whisper-cpp")
WHISPER_CLI = os.path.join(WHISPER_DIR, "whisper-cli.exe")
WHISPER_SERVER = os.path.join(WHISPER_DIR, "whisper-server.exe")
MODELS_DIR = os.path.join(WHISPER_DIR, "models")

# medium braucht auf langsamen Platten lange zum Laden
_SERVER_START_TIMEOUT_S = 90
_REQUEST_TIMEOUT_S = 60


def _threads() -> int:
    """Heuristik fuer physische Kerne (os.cpu_count() zaehlt logische).

    Mehr als 8 Threads bringen bei whisper.cpp kaum noch etwas.
    """
    return max(2, min(8, (os.cpu_count() or 8) // 2))


def _quality_args(performance_mode: str) -> dict:
    """Beam-Search-Parameter: greedy fuer Diktat (3-5x schneller), Beam 5 fuer Qualitaet."""
    if performance_mode == "quality":
        return {"beam_size": 5, "best_of": 5}
    return {"beam_size": 1, "best_of": 1}


def _clean_output(text: str) -> str:
    """Entfernt Whisper-Marker wie [MUSIK], [BLANK_AUDIO] und normalisiert Whitespace."""
    if not text:
        return ""
    text = re.sub(r"\[.*?\]", "", text)
    return " ".join(text.split()).strip()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _exit_code_hint(code: int) -> str:
    """Verstaendliche Erklaerung fuer einen whisper-Exit-Code ("" wenn keine)."""
    key = classify_win_exit_code(code)
    return t(key, url=VCREDIST_URL) if key else ""


def is_setup_complete(model_size: str) -> bool:
    """Binary + Modell vorhanden — reine Dateipruefung, ohne Backend-Aufbau
    (kein Job-Object, kein atexit-Handler)."""
    if not os.path.isfile(WHISPER_CLI):
        return False
    model_path = os.path.join(MODELS_DIR, MODEL_FILES.get(model_size, "ggml-small.bin"))
    if not os.path.isfile(model_path):
        return False
    return os.path.getsize(model_path) >= MODEL_MIN_SIZES.get(model_size, 0)


class CliBackend:
    """Ein whisper-cli.exe-Aufruf pro Transkription (Modell laedt jedes Mal neu)."""

    def __init__(self, model_path: str, language: str, performance_mode: str):
        self.model_path = model_path
        self.language = language
        self.performance_mode = performance_mode
        self.last_error_hint = ""

    def transcribe(self, wav_path: str) -> str:
        q = _quality_args(self.performance_mode)
        cmd = [
            WHISPER_CLI,
            "-m", self.model_path,
            "-f", wav_path,
            "-l", self.language,
            "-nt",
            "-t", str(_threads()),
            "-bo", str(q["best_of"]),
            "-bs", str(q["beam_size"]),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_REQUEST_TIMEOUT_S,
                creationflags=subprocess.CREATE_NO_WINDOW,
                cwd=WHISPER_DIR,
            )
        except subprocess.TimeoutExpired:
            log.warning("whisper-cli Timeout nach %ds", _REQUEST_TIMEOUT_S)
            return ""
        except FileNotFoundError as e:
            log.error("whisper-cli nicht gefunden: %s", e)
            return ""

        if result.returncode != 0:
            self.last_error_hint = _exit_code_hint(result.returncode)
            log.error("whisper-cli Fehler (code %d): %s %s",
                      result.returncode, result.stderr[:500], self.last_error_hint)
            return ""

        self.last_error_hint = ""
        return result.stdout.strip()


class ServerBackend:
    """Persistenter whisper-server.exe — Modell bleibt im RAM.

    Lazy-Start mit /health-Polling; bei Crash/Request-Fehler genau ein
    Neustartversuch, danach Exception (Caller faellt auf CLI zurueck).
    Lauscht ausschliesslich auf 127.0.0.1.
    """

    def __init__(self, model_path: str, language: str, performance_mode: str):
        self.model_path = model_path
        self.language = language
        self.performance_mode = performance_mode
        self._proc = None
        self._port = None
        self._lock = threading.RLock()
        self.last_error_hint = ""
        # Job-Object haelt den Server an unseren Prozess gekettet: stirbt VoZii
        # (auch per Force-Kill/Crash), killt Windows den Server automatisch.
        # atexit erst bei laufendem Prozess registrieren (_start) und in
        # shutdown() wieder abmelden — sonst akkumulieren sich Handler ueber
        # Settings-Roundtrips.
        self._job = create_kill_on_close_job()

    def ensure_started(self):
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return
            self._start()

    def _start(self):
        self._port = _free_port()
        cmd = [
            WHISPER_SERVER,
            "-m", self.model_path,
            "--host", "127.0.0.1",
            "--port", str(self._port),
            "-t", str(_threads()),
        ]
        log.info("Starte whisper-server (Port %d, Modell %s)",
                 self._port, os.path.basename(self.model_path))
        # stdout/stderr nach DEVNULL: der Server loggt jeden Request — eine
        # PIPE wuerde ueber lange Sessions volllaufen und den Prozess blocken.
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            cwd=WHISPER_DIR,
        )
        if self._job:
            assign_process_to_job(self._job, self._proc.pid)
        atexit.register(self.shutdown)

        deadline = time.time() + _SERVER_START_TIMEOUT_S
        while time.time() < deadline:
            if self._proc.poll() is not None:
                code = self._proc.returncode
                self._proc = None
                self.last_error_hint = _exit_code_hint(code)
                hint = f"\n{self.last_error_hint}" if self.last_error_hint else ""
                raise RuntimeError(f"whisper-server sofort beendet (Code {code}){hint}")
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{self._port}/health", timeout=2) as resp:
                    if resp.status == 200:
                        log.info("whisper-server bereit")
                        return
            except (urllib.error.URLError, OSError):
                pass  # laedt noch (503) oder lauscht noch nicht
            time.sleep(0.25)

        self.shutdown()
        raise RuntimeError(f"whisper-server Start-Timeout ({_SERVER_START_TIMEOUT_S}s)")

    def transcribe(self, wav_path: str) -> str:
        self.ensure_started()
        try:
            return self._request(wav_path)
        except Exception as e:
            # Ein Neustartversuch — deckt Server-Crash und Standby-Resume ab
            log.warning("whisper-server Request fehlgeschlagen (%s) — Neustart", e)
            self.shutdown()
            self.ensure_started()
            return self._request(wav_path)

    def _request(self, wav_path: str) -> str:
        q = _quality_args(self.performance_mode)
        fields = {
            "language": self.language,
            "response_format": "json",
            "no_timestamps": "true",
            "beam_size": str(q["beam_size"]),
            "best_of": str(q["best_of"]),
        }
        with open(wav_path, "rb") as f:
            wav_data = f.read()
        body, content_type = _build_multipart(fields, "file", "audio.wav", wav_data)

        req = urllib.request.Request(
            f"http://127.0.0.1:{self._port}/inference",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        if data.get("error"):
            raise RuntimeError(f"whisper-server: {data['error']}")
        return data.get("text", "").strip()

    def shutdown(self):
        atexit.unregister(self.shutdown)
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        log.info("Beende whisper-server")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                log.warning("whisper-server liess sich nicht beenden")


def _build_multipart(fields: dict, file_field: str, filename: str,
                     file_data: bytes) -> tuple[bytes, str]:
    """multipart/form-data ohne externe Abhaengigkeit (kein requests)."""
    boundary = uuid.uuid4().hex
    body = io.BytesIO()
    for name, value in fields.items():
        body.write(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode()
        )
    body.write(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        f"Content-Type: audio/wav\r\n\r\n".encode()
    )
    body.write(file_data)
    body.write(f"\r\n--{boundary}--\r\n".encode())
    return body.getvalue(), f"multipart/form-data; boundary={boundary}"


class Transcriber:
    """Facade: Server-Backend wenn verfuegbar, sonst (und bei Fehlern) CLI."""

    def __init__(self, model_size: str = "large-v3-turbo-q5_0", language: str = "de",
                 performance_mode: str = "speed", use_server: bool = True):
        self.model_size = model_size
        self.language = language
        self.model_path = os.path.join(MODELS_DIR, MODEL_FILES.get(model_size, "ggml-small.bin"))
        self._cli = CliBackend(self.model_path, language, performance_mode)
        self._server = None
        if use_server and is_server_available():
            self._server = ServerBackend(self.model_path, language, performance_mode)
        log.info("Transcriber-Backend: %s", "server" if self._server else "cli")

    @property
    def last_error_hint(self) -> str:
        """Verstaendliche Erklaerung des letzten Backend-Fehlers ("" wenn keiner) —
        z. B. Smart-App-Control-Block oder fehlende VC++-Runtime."""
        if self._server is not None and self._server.last_error_hint:
            return self._server.last_error_hint
        return self._cli.last_error_hint

    def is_ready(self) -> bool:
        return is_setup_complete(self.model_size)

    def warmup(self):
        """Startet den Server im Hintergrund, damit die erste Transkription
        nicht auf das Modell-Laden warten muss. Best-effort."""
        if self._server is None:
            return
        try:
            self._server.ensure_started()
        except Exception:
            log.exception("Server-Warmup fehlgeschlagen (CLI-Fallback bleibt)")

    def transcribe(self, wav_path: str) -> str:
        if not self.is_ready():
            raise FileNotFoundError(
                f"whisper-cli.exe oder Modell nicht gefunden/corrupt.\n"
                f"CLI: {WHISPER_CLI}\nModell: {self.model_path}"
            )
        if self._server is not None:
            try:
                return _clean_output(self._server.transcribe(wav_path))
            except Exception:
                log.exception("Server-Backend fehlgeschlagen — Fallback auf CLI")
        return _clean_output(self._cli.transcribe(wav_path))

    def shutdown(self):
        if self._server is not None:
            self._server.shutdown()

    def get_status(self) -> str:
        if not os.path.isfile(WHISPER_CLI):
            return t("transcriber.cli_missing", path=WHISPER_CLI)
        if not os.path.isfile(self.model_path):
            return t("transcriber.model_missing", path=self.model_path)
        min_size = MODEL_MIN_SIZES.get(self.model_size, 0)
        actual = os.path.getsize(self.model_path)
        if actual < min_size:
            return t("transcriber.model_incomplete",
                     actual=actual // 1048576, min=min_size // 1048576)
        backend = "Server" if self._server is not None else "CLI"
        return t("transcriber.ready", model=self.model_size,
                 lang=self.language, backend=backend)
