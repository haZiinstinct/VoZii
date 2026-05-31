import logging
import os
import re
import subprocess

from src.paths import BASE_DIR
from src.downloader import MODEL_MIN_SIZES
from src.platform_utils import find_whisper_cli, whisper_cli_name, SUBPROCESS_FLAGS, IS_MAC

log = logging.getLogger(__name__)

WHISPER_DIR = os.path.join(BASE_DIR, "whisper-cpp")
MODELS_DIR = os.path.join(WHISPER_DIR, "models")

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
        # whisper.cpp CLI zur Laufzeit aufloesen (Brew-Binary kann nach Import erscheinen).
        self.cli = find_whisper_cli(WHISPER_DIR)

    def is_ready(self) -> bool:
        # Neu aufloesen, falls die CLI erst nach __init__ installiert wurde.
        self.cli = find_whisper_cli(WHISPER_DIR)
        if not self.cli or not os.path.isfile(self.cli):
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
                f"whisper.cpp CLI ({whisper_cli_name()}) oder Modell nicht gefunden/corrupt.\n"
                f"CLI: {self.cli}\nModell: {self.model_path}"
            )

        cmd = [
            self.cli,
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
                creationflags=SUBPROCESS_FLAGS,
                cwd=os.path.dirname(self.cli),
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
        self.cli = find_whisper_cli(WHISPER_DIR)
        if not self.cli or not os.path.isfile(self.cli):
            hint = "  (macOS: 'brew install whisper-cpp')" if IS_MAC else ""
            return f"whisper.cpp CLI fehlt{hint}"
        if not os.path.isfile(self.model_path):
            return f"Modell fehlt: {self.model_path}"
        min_size = MODEL_MIN_SIZES.get(self.model_size, 0)
        actual = os.path.getsize(self.model_path)
        if actual < min_size:
            return f"Modell unvollstaendig ({actual // 1048576} MB, erwartet >= {min_size // 1048576} MB)"
        return f"Bereit (Modell: {self.model_size}, Sprache: {self.language})"
