import logging
import os
import re
import subprocess

from src.paths import BASE_DIR
from src.downloader import MODEL_MIN_SIZES

log = logging.getLogger(__name__)

WHISPER_CLI = os.path.join(BASE_DIR, "whisper-cpp", "whisper-cli.exe")
MODELS_DIR = os.path.join(BASE_DIR, "whisper-cpp", "models")

MODEL_FILES = {
    "tiny": "ggml-tiny.bin",
    "small": "ggml-small.bin",
    "medium": "ggml-medium.bin",
}


class Transcriber:
    def __init__(self, model_size: str = "small", language: str = "de"):
        self.model_size = model_size
        self.language = language
        self.model_path = os.path.join(MODELS_DIR, MODEL_FILES.get(model_size, "ggml-small.bin"))

    def is_ready(self) -> bool:
        if not os.path.isfile(WHISPER_CLI):
            return False
        if not os.path.isfile(self.model_path):
            return False
        min_size = MODEL_MIN_SIZES.get(self.model_size, 0)
        if os.path.getsize(self.model_path) < min_size:
            return False
        return True

    def transcribe(self, wav_path: str) -> str:
        if not self.is_ready():
            raise FileNotFoundError(
                f"whisper-cli.exe oder Modell nicht gefunden/corrupt.\n"
                f"CLI: {WHISPER_CLI}\nModell: {self.model_path}"
            )

        cmd = [
            WHISPER_CLI,
            "-m", self.model_path,
            "-f", wav_path,
            "-l", self.language,
            "-nt",
            "-bo", "5",
            "-bs", "5",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW,
                cwd=os.path.dirname(WHISPER_CLI),
            )
        except subprocess.TimeoutExpired:
            log.warning("whisper-cli Timeout nach 60s")
            return ""
        except FileNotFoundError as e:
            log.error("whisper-cli nicht gefunden: %s", e)
            return ""

        if result.returncode != 0:
            log.error("whisper-cli Fehler (code %d): %s",
                      result.returncode, result.stderr[:500])
            return ""

        text = result.stdout.strip()
        if not text:
            return ""

        # Remove whisper markers like [MUSIK], [BLANK_AUDIO], etc.
        text = re.sub(r"\[.*?\]", "", text)
        text = " ".join(text.split())
        return text.strip()

    def get_status(self) -> str:
        if not os.path.isfile(WHISPER_CLI):
            return f"whisper-cli.exe fehlt: {WHISPER_CLI}"
        if not os.path.isfile(self.model_path):
            return f"Modell fehlt: {self.model_path}"
        min_size = MODEL_MIN_SIZES.get(self.model_size, 0)
        actual = os.path.getsize(self.model_path)
        if actual < min_size:
            return f"Modell unvollstaendig ({actual // 1048576} MB, erwartet >= {min_size // 1048576} MB)"
        return f"Bereit (Modell: {self.model_size}, Sprache: {self.language})"
