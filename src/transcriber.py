"""Transkription — whisper.cpp (Server + CLI-Fallback) oder Parakeet (CPU).

ServerBackend haelt das Modell im RAM (whisper-server.exe, nur 127.0.0.1):
spart das Neu-Laden des Modells (75 MB - 1,5 GB) bei jeder Transkription.
CliBackend ist der robuste Fallback (whisper-cli.exe pro Aufruf).
ParakeetBackend (src/parakeet.py) ist die schnelle CPU-Engine fuer
EU-Sprachen. Stuerzt ein GPU-Backend ab, faellt der Transcriber einmalig
auf CPU zurueck — bevorzugt auf Parakeet, sonst whisper.cpp mit --no-gpu.
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
import wave

import numpy as np

from src.downloader import (
    MODEL_FILES,
    MODEL_MIN_SIZES,
    PARAKEET_DIR,
    PARAKEET_MODEL,
    installed_backend_type,
    is_model_installed,
    is_parakeet,
    is_server_available,
)
from src.errors import VCREDIST_URL, classify_win_exit_code
from src.i18n import t
from src.parakeet import ParakeetBackend, supports_language
from src.paths import BASE_DIR, TMP_DIR
from src.winutil import assign_process_to_job, close_handle, create_kill_on_close_job

log = logging.getLogger(__name__)

# Loopback-Opener ohne System-Proxy: auf Firmen-/VPN-Rechnern schickt
# urllib.request.urlopen() Anfragen an 127.0.0.1 sonst ueber den Proxy und
# liest zudem bei jedem Aufruf die Windows-Registry aus.
_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_ORIG_URLOPEN = urllib.request.urlopen


def _local_urlopen(req, timeout: float):
    if urllib.request.urlopen is not _ORIG_URLOPEN:
        return urllib.request.urlopen(req, timeout=timeout)
    return _LOCAL_OPENER.open(req, timeout=timeout)

WHISPER_DIR = os.path.join(BASE_DIR, "whisper-cpp")
WHISPER_CLI = os.path.join(WHISPER_DIR, "whisper-cli.exe")
WHISPER_SERVER = os.path.join(WHISPER_DIR, "whisper-server.exe")
MODELS_DIR = os.path.join(WHISPER_DIR, "models")

# medium braucht auf langsamen Platten lange zum Laden
_SERVER_START_TIMEOUT_S = 90
# Untergrenze; der echte Timeout waechst mit der Aufnahmelaenge (_timeout_for).
# Fest 60s haben lange Diktate im Qualitaetsmodus abgeschnitten — die Aufnahme
# war dann weg, obwohl die Transkription nur ein paar Sekunden gefehlt haetten.
_REQUEST_TIMEOUT_S = 60
# 16 kHz mono, 16 Bit -> Bytes pro Sekunde Audio
_WAV_BYTES_PER_S = 16000 * 2
# Live-Vorschau: kurzer Timeout, eine haengende Vorschau ist wertlos
_PREVIEW_TIMEOUT_S = 5


class TranscriptionTimeout(Exception):
    """Transkription lief in den Timeout — Aufnahme zu lang fuer Modus/Hardware.

    Kein Server-Neustart und kein CLI-Fallback: beides wuerde denselben
    Timeout noch zweimal abwarten, waehrend der Worker steht."""


def _is_timeout(e: BaseException) -> bool:
    # Beim Lesen kommt TimeoutError direkt, beim Verbinden in URLError verpackt
    return isinstance(e, TimeoutError) or (
        isinstance(e, urllib.error.URLError) and isinstance(e.reason, TimeoutError))


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


def _timeout_for(audio_or_path) -> int:
    """Timeout passend zur Aufnahmelaenge (Minimum _REQUEST_TIMEOUT_S).

    Faustregel: bis zum Vierfachen der Audiolaenge plus Anlauf — deckt auch
    den Qualitaetsmodus (Beam 5) auf reiner CPU ab.
    """
    if isinstance(audio_or_path, np.ndarray):
        duration = len(audio_or_path) / 16000.0
    else:
        try:
            duration = os.path.getsize(audio_or_path) / _WAV_BYTES_PER_S
        except OSError:
            duration = 0.0
    return max(_REQUEST_TIMEOUT_S, int(duration * 4) + 30)


def _wav_bytes(audio) -> bytes:
    """float32-Audio (16 kHz mono) -> WAV-Datei im Speicher."""
    pcm = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def _child_env() -> dict:
    """Umgebung fuer whisper-cli/-server ohne VoZiis OPENBLAS_NUM_THREADS=1.

    Die Begrenzung gilt nur fuer numpy im VoZii-Prozess; whisper.cpp soll
    seine BLAS-Threads selbst nach -t setzen."""
    env = dict(os.environ)
    if os.environ.get("VOZII_OPENBLAS_SET") == "1":
        env.pop("OPENBLAS_NUM_THREADS", None)
    env.pop("VOZII_OPENBLAS_SET", None)
    return env


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
    (kein Job-Object, kein atexit-Handler). Parakeet braucht kein whisper-Binary."""
    if is_parakeet(model_size):
        return is_model_installed(model_size)
    if not os.path.isfile(WHISPER_CLI):
        return False
    model_path = os.path.join(MODELS_DIR, MODEL_FILES.get(model_size, "ggml-small.bin"))
    if not os.path.isfile(model_path):
        return False
    return os.path.getsize(model_path) >= MODEL_MIN_SIZES.get(model_size, 0)


class CliBackend:
    """Ein whisper-cli.exe-Aufruf pro Transkription (Modell laedt jedes Mal neu)."""

    def __init__(self, model_path: str, language: str, performance_mode: str,
                 initial_prompt: str = ""):
        self.model_path = model_path
        self.language = language
        self.performance_mode = performance_mode
        self.initial_prompt = initial_prompt
        self.no_gpu = False
        self.last_error_hint = ""
        self.last_returncode = None

    def transcribe(self, audio_or_path: str | np.ndarray) -> str:
        self.last_returncode = None
        temp_wav = None
        if isinstance(audio_or_path, np.ndarray):
            os.makedirs(TMP_DIR, exist_ok=True)
            temp_wav = os.path.join(TMP_DIR, f"vozii_cli_{os.getpid()}_{uuid.uuid4().hex[:8]}.wav")
            with open(temp_wav, "wb") as f:
                f.write(_wav_bytes(audio_or_path))
            wav_path = temp_wav
        else:
            wav_path = audio_or_path

        try:
            timeout_s = _timeout_for(wav_path)
            q = _quality_args(self.performance_mode)
            cmd = [
                WHISPER_CLI,
                "-m", self.model_path,
                "-f", wav_path,
                "-l", self.language,
                "-nt",
                "-sns",
                "-t", str(_threads()),
                "-bo", str(q["best_of"]),
                "-bs", str(q["beam_size"]),
            ]
            if self.initial_prompt:
                # Eigene Begriffe (Namen, Fachwoerter) als Erkennungs-Kontext —
                # carry-initial-prompt haelt sie auch ueber 30 s hinaus aktiv
                cmd += ["--prompt", self.initial_prompt, "--carry-initial-prompt"]
            if self.no_gpu:
                cmd.append("-ng")

            try:
                result = subprocess.run(
                    cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_s,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    cwd=WHISPER_DIR,
                    env=_child_env(),
                )
            except subprocess.TimeoutExpired:
                log.warning("whisper-cli Timeout nach %ds", timeout_s)
                return ""
            except FileNotFoundError as e:
                log.error("whisper-cli nicht gefunden: %s", e)
                return ""

            self.last_returncode = result.returncode
            if result.returncode != 0:
                self.last_error_hint = _exit_code_hint(result.returncode)
                log.error("whisper-cli Fehler (code %d): %s %s",
                          result.returncode, result.stderr[:500], self.last_error_hint)
                return ""

            self.last_error_hint = ""
            return result.stdout.strip()
        finally:
            if temp_wav is not None:
                try:
                    os.remove(temp_wav)
                except OSError:
                    pass


class ServerBackend:
    """Persistenter whisper-server.exe — Modell bleibt im RAM.

    Lazy-Start mit /health-Polling; bei Crash/Request-Fehler genau ein
    Neustartversuch, danach Exception (Caller faellt auf CLI zurueck).
    Lauscht ausschliesslich auf 127.0.0.1.
    """

    def __init__(self, model_path: str, language: str, performance_mode: str,
                 initial_prompt: str = ""):
        self.model_path = model_path
        self.language = language
        self.performance_mode = performance_mode
        self.initial_prompt = initial_prompt
        self._proc = None
        self._port = None
        self._lock = threading.RLock()
        self.no_gpu = False
        self.last_error_hint = ""
        # Job-Object haelt den Server an unseren Prozess gekettet: stirbt VoZii
        # (auch per Force-Kill/Crash), killt Windows den Server automatisch.
        # atexit erst bei laufendem Prozess registrieren (_start) und in
        # shutdown() wieder abmelden — sonst akkumulieren sich Handler ueber
        # Settings-Roundtrips.
        self._job = create_kill_on_close_job()

    @property
    def running(self) -> bool:
        proc = self._proc
        return proc is not None and proc.poll() is None

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
        if self.no_gpu:
            cmd.append("-ng")
        log.info("Starte whisper-server (Port %d, Modell %s%s)",
                 self._port, os.path.basename(self.model_path),
                 ", CPU" if self.no_gpu else "")
        # stdout/stderr nach DEVNULL: der Server loggt jeden Request — eine
        # PIPE wuerde ueber lange Sessions volllaufen und den Prozess blocken.
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            cwd=WHISPER_DIR,
            env=_child_env(),
        )
        if self._job is None:
            self._job = create_kill_on_close_job()
        if self._job:
            assign_process_to_job(self._job, self._proc.pid)
        atexit.register(self.shutdown)

        started_at = time.monotonic()
        deadline = started_at + _SERVER_START_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                code = self._proc.returncode
                self._proc = None
                self.last_error_hint = _exit_code_hint(code)
                hint = f"\n{self.last_error_hint}" if self.last_error_hint else ""
                raise RuntimeError(f"whisper-server sofort beendet (Code {code}){hint}")
            try:
                with _local_urlopen(
                        f"http://127.0.0.1:{self._port}/health", timeout=2) as resp:
                    if resp.status == 200:
                        log.info("whisper-server bereit (%.2fs)", time.monotonic() - started_at)
                        return
            except (urllib.error.URLError, OSError):
                pass  # laedt noch (503) oder lauscht noch nicht
            elapsed = time.monotonic() - started_at
            time.sleep(0.05 if elapsed < 2.0 else (0.15 if elapsed < 8.0 else 0.25))

        self.shutdown()
        raise RuntimeError(f"whisper-server Start-Timeout ({_SERVER_START_TIMEOUT_S}s)")

    def transcribe(self, audio_or_path: str | np.ndarray) -> str:
        self.ensure_started()
        try:
            return self._request(audio_or_path)
        except Exception as e:
            # Timeout bei laufendem Server = Aufnahme zu lang, kein Crash
            if _is_timeout(e) and self._proc is not None and self._proc.poll() is None:
                raise TranscriptionTimeout(str(e)) from e
            # Ein Neustartversuch — deckt Server-Crash und Standby-Resume ab
            log.warning("whisper-server Request fehlgeschlagen (%s) — Neustart", e)
            self.shutdown()
            self.ensure_started()
            return self._request(audio_or_path)

    def preview(self, audio) -> str | None:
        """Live-Vorschau: greedy, kurzer Timeout, kein Neustart. Laeuft der
        Server (noch) nicht, None — die Vorschau startet nichts selbst."""
        if not self.running:
            return None
        try:
            return self._post(_wav_bytes(audio), "speed", _PREVIEW_TIMEOUT_S)
        except Exception as e:
            log.debug("Vorschau-Request fehlgeschlagen: %s", e)
            return None

    def _request(self, audio_or_path: str | np.ndarray) -> str:
        if isinstance(audio_or_path, np.ndarray):
            wav_data = _wav_bytes(audio_or_path)
        else:
            with open(audio_or_path, "rb") as f:
                wav_data = f.read()
        return self._post(wav_data, self.performance_mode, _timeout_for(audio_or_path))

    def _post(self, wav_data: bytes, performance_mode: str, timeout_s: float) -> str:
        q = _quality_args(performance_mode)
        fields = {
            "language": self.language,
            "response_format": "json",
            "no_timestamps": "true",
            "beam_size": str(q["beam_size"]),
            "best_of": str(q["best_of"]),
        }
        if self.initial_prompt:
            fields["prompt"] = self.initial_prompt
        body, content_type = _build_multipart(fields, "file", "audio.wav", wav_data)

        req = urllib.request.Request(
            f"http://127.0.0.1:{self._port}/inference",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        with _local_urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        if data.get("error"):
            raise RuntimeError(f"whisper-server: {data['error']}")
        return data.get("text", "").strip()

    def shutdown(self):
        atexit.unregister(self.shutdown)
        with self._lock:
            proc, self._proc = self._proc, None
            job, self._job = getattr(self, "_job", None), None
        try:
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
        finally:
            close_handle(job)


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
    """Facade ueber die Engines.

    Whisper: Server-Backend wenn verfuegbar, sonst (und bei Fehlern) CLI;
    stuerzt ein GPU-Backend ab, einmalig CPU-Fallback.
    Parakeet: in-process auf der CPU; fuer Sprachen ausserhalb der 25
    EU-Sprachen (und falls Parakeet versagt) springt Whisper ein, sofern
    installiert (whisper_model)."""

    engine = "whisper"
    notice = ""  # einmaliger Hinweis fuers Overlay ("cpu_fallback")
    _parakeet = None
    _no_gpu = False
    _preparing = False

    def __init__(self, model_size: str = "large-v3-turbo-q5_0", language: str = "de",
                 performance_mode: str = "speed", use_server: bool = True,
                 initial_prompt: str = "", whisper_model: str = "large-v3-turbo-q5_0"):
        self.model_size = model_size
        self.language = language
        self._prepare_lock = threading.Lock()
        if not is_parakeet(model_size):
            whisper_model = model_size
        self.whisper_model = whisper_model
        self.model_path = os.path.join(MODELS_DIR, MODEL_FILES.get(whisper_model, "ggml-small.bin"))
        self._is_gpu = self._gpu_backend()

        if (is_parakeet(model_size) or self._is_gpu) and supports_language(language) \
                and is_model_installed(PARAKEET_MODEL):
            # Bei Whisper-auf-GPU nur als CPU-Reserve angelegt (laedt erst bei Bedarf)
            self._parakeet = ParakeetBackend(_threads())
        elif is_parakeet(model_size) and not supports_language(language):
            log.warning("Sprache %r kann Parakeet nicht — nutze Whisper (%s)",
                        language, whisper_model)
        self.engine = ("parakeet" if is_parakeet(model_size) and self._parakeet is not None
                       else "whisper")

        whisper_wanted = self.engine == "whisper" or is_setup_complete(whisper_model)
        self._cli = CliBackend(self.model_path, language, performance_mode, initial_prompt)
        self._server = None
        if whisper_wanted and use_server and is_server_available():
            self._server = ServerBackend(self.model_path, language, performance_mode,
                                         initial_prompt)
        self._whisper_ok = is_setup_complete(whisper_model)
        log.info("Transcriber-Engine: %s", "parakeet (cpu)" if self.engine == "parakeet"
                 else ("whisper (server)" if self._server else "whisper (cli)"))

    @staticmethod
    def _gpu_backend() -> bool:
        return installed_backend_type() in ("nvidia", "amd")

    @property
    def last_error_hint(self) -> str:
        """Verstaendliche Erklaerung des letzten Backend-Fehlers ("" wenn keiner) —
        z. B. Smart-App-Control-Block oder fehlende VC++-Runtime."""
        if self.engine == "parakeet" and self._parakeet.last_error_hint:
            return self._parakeet.last_error_hint
        if self._server is not None and self._server.last_error_hint:
            return self._server.last_error_hint
        return self._cli.last_error_hint

    def is_ready(self) -> bool:
        if self.engine == "parakeet":
            return True
        return self._whisper_ok

    def warmup(self):
        """Laedt das Modell (Parakeet in-process, sonst den whisper-server),
        damit die Transkription nicht darauf wartet. Best-effort und
        wiederholbar: ist das Modell schon da, passiert nichts."""
        try:
            if self.engine == "parakeet":
                self._parakeet.warmup()
            elif self._server is not None:
                self._server.ensure_started()
        except Exception:
            log.exception("Warmup fehlgeschlagen (Fallback bleibt)")

    def prepare_async(self):
        """warmup() im Hintergrund — z. B. beim Hotkey-Druck, damit das
        Laden parallel zur Aufnahme laeuft. Kein zweiter Thread, solange
        einer noch laedt."""
        if self.loaded:
            return
        with self._prepare_lock:
            if self._preparing:
                return
            self._preparing = True

        def run():
            try:
                self.warmup()
            finally:
                with self._prepare_lock:
                    self._preparing = False

        threading.Thread(target=run, daemon=True, name="model-prepare").start()

    @property
    def loaded(self) -> bool:
        """Liegt das Modell der aktiven Engine im RAM?"""
        if self.engine == "parakeet":
            return self._parakeet.loaded
        if self._server is not None:
            return self._server.running
        return True  # CLI laedt pro Aufruf, haelt nichts im RAM

    def release(self) -> bool:
        """Modell aus dem RAM nehmen (Leerlauf). Die naechste Transkription
        bzw. prepare_async() laedt es neu. True, wenn etwas entladen wurde."""
        freed = False
        if self._parakeet is not None:
            freed = self._parakeet.release()
        if self._server is not None and self._server.running:
            self._server.shutdown()
            freed = True
        return freed

    def transcribe(self, wav_path: str) -> str:
        if not self.is_ready():
            raise FileNotFoundError(
                f"whisper-cli.exe oder Modell nicht gefunden/corrupt.\n"
                f"CLI: {WHISPER_CLI}\nModell: {self.model_path}"
            )
        if self.engine == "parakeet":
            try:
                return _clean_output(self._parakeet.transcribe(wav_path))
            except Exception:
                if not self._whisper_ok:
                    raise
                log.exception("Parakeet fehlgeschlagen — Fallback auf Whisper")
        return self._transcribe_whisper(wav_path)

    def _live_backend(self):
        """Backend, das schnell genug fuer die Live-Vorschau ist (sonst None).
        Parakeet immer, Whisper nur als Server auf der GPU — Whisper auf der
        CPU wuerde mit dem Diktat um die Kerne konkurrieren und haengt
        ohnehin hinterher."""
        if self.engine == "parakeet":
            return self._parakeet
        if self._server is not None and not self._no_gpu:
            is_gpu = getattr(self, "_is_gpu", None)
            if is_gpu is None:
                is_gpu = self._gpu_backend()
            if is_gpu:
                return self._server
        return None

    @property
    def live_capable(self) -> bool:
        return self._live_backend() is not None

    def preview(self, audio) -> str:
        """Vorschautext fuer einen Audio-Ausschnitt ("" wenn gerade nichts
        geht). Blockiert nie auf die eigentliche Transkription und loest
        keinen Fallback aus. Ein beim Loslassen noch laufender Durchlauf
        verzoegert die Transkription um seine Restlaufzeit (gemessen: im
        Mittel ~0,15 s, siehe scripts/bench_live.py)."""
        try:
            backend = self._live_backend()
            if backend is None:
                return ""
            text = backend.preview(audio)
        except Exception:
            log.debug("Vorschau fehlgeschlagen", exc_info=True)
            return ""
        return _clean_output(text or "")

    def _transcribe_whisper(self, wav_path: str) -> str:
        text = self._whisper_once(wav_path)
        if text or not self._gpu_crashed():
            return text
        # GPU-Backend abgestuerzt (Treiber, VRAM, kaputtes CUDA) -> fuer den
        # Rest des Zyklus auf CPU; Parakeet ist dort deutlich schneller
        log.warning("GPU-Backend abgestuerzt (Code %s) — wechsle auf CPU",
                    self._cli.last_returncode)
        self._switch_to_cpu()
        if self.engine == "parakeet":
            return _clean_output(self._parakeet.transcribe(wav_path))
        return self._whisper_once(wav_path)

    def _whisper_once(self, wav_path: str) -> str:
        if self._server is not None:
            try:
                return _clean_output(self._server.transcribe(wav_path))
            except TranscriptionTimeout:
                raise
            except Exception:
                log.exception("Server-Backend fehlgeschlagen — Fallback auf CLI")
        return _clean_output(self._cli.transcribe(wav_path))

    def _gpu_crashed(self) -> bool:
        """CLI mit Crash-Code beendet, waehrend ein GPU-Backend installiert ist.

        SAC-Block und fehlende VC++-Runtime treffen die CPU genauso — dort
        bringt der Wechsel nichts."""
        code = getattr(self._cli, "last_returncode", None)
        if self._no_gpu or not code or not self._gpu_backend():
            return False
        return classify_win_exit_code(code) not in ("err.hint.sac", "err.hint.vcredist")

    def _switch_to_cpu(self):
        self._no_gpu = True
        self.notice = "cpu_fallback"
        self._cli.no_gpu = True
        if self._server is not None:
            self._server.shutdown()
            self._server.no_gpu = True
        if self._parakeet is not None:
            self.engine = "parakeet"

    def pop_notice(self) -> str:
        notice, self.notice = self.notice, ""
        return notice

    def shutdown(self):
        if self._server is not None:
            self._server.shutdown()
        if self._parakeet is not None:
            self._parakeet.shutdown()

    def get_status(self) -> str:
        if self.engine == "parakeet":
            return t("transcriber.ready", model="Parakeet v3", lang=self.language,
                     backend="CPU")
        if is_parakeet(self.model_size) and not self._whisper_ok:
            if not supports_language(self.language):
                return t("transcriber.parakeet_lang", lang=self.language)
            return t("transcriber.model_missing", path=PARAKEET_DIR)
        if not os.path.isfile(WHISPER_CLI):
            return t("transcriber.cli_missing", path=WHISPER_CLI)
        if not os.path.isfile(self.model_path):
            return t("transcriber.model_missing", path=self.model_path)
        min_size = MODEL_MIN_SIZES.get(self.whisper_model, 0)
        actual = os.path.getsize(self.model_path)
        if actual < min_size:
            return t("transcriber.model_incomplete",
                     actual=actual // 1048576, min=min_size // 1048576)
        backend = "Server" if self._server is not None else "CLI"
        return t("transcriber.ready", model=self.whisper_model,
                 lang=self.language, backend=backend)
