import os
import re
import subprocess

from src.paths import BASE_DIR

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
        return os.path.isfile(WHISPER_CLI) and os.path.isfile(self.model_path)

    def transcribe(self, wav_path: str) -> str:
        if not self.is_ready():
            raise FileNotFoundError(
                f"whisper-cli.exe oder Modell nicht gefunden.\n"
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
                cwd=os.path.dirname(WHISPER_CLI),  # Run from whisper-cpp dir for DLL resolution
            )
        except subprocess.TimeoutExpired:
            print("[WHISPER] Timeout nach 60s")
            return ""
        except FileNotFoundError as e:
            print(f"[WHISPER] Nicht gefunden: {e}")
            return ""

        if result.returncode != 0:
            print(f"[WHISPER] Fehler (code {result.returncode}): {result.stderr[:200]}")
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
        return f"Bereit (Modell: {self.model_size}, Sprache: {self.language})"
