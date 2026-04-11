"""Text Post-Processing via Ollama (lokal) + Ollama Install/Pull Management."""

import json
import logging
import os
import subprocess
import tempfile
import time
import urllib.request

log = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434"
OLLAMA_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
DEFAULT_MODEL = "llama3.2:3b"

PROMPTS = {
    "clean": (
        "Korrigiere den folgenden gesprochenen Text. Entferne Fuellwoerter "
        "(aehm, also, ja, halt, ne). Korrigiere Grammatik und Interpunktion. "
        "Aendere NICHT den Inhalt oder die Bedeutung. Behalte die "
        "Originalsprache bei. Gib NUR den korrigierten Text zurueck, "
        "keine Erklaerung, keine Anfuehrungszeichen.\n\n"
        "Text: {text}\n\nKorrigiert:"
    ),
    "format": (
        "Wandle den folgenden gesprochenen Text in eine gut strukturierte, "
        "lesbare Form um. Entferne Fuellwoerter, korrigiere Grammatik. "
        "Nutze Markdown-Formatierung wo sinnvoll: Ueberschriften (##), "
        "Listen mit Bullet Points (-), Fettschrift (**...**), Absaetze. "
        "KEINE Email-Formulierungen wie 'Sehr geehrte' oder 'Mit freundlichen "
        "Gruessen'. Behalte die Originalsprache bei. Gib NUR den formatierten "
        "Text zurueck, keine Erklaerung.\n\n"
        "Text: {text}\n\nFormatiert:"
    ),
    "prompt": (
        "Wandle den folgenden gesprochenen Text in einen klaren, strukturierten "
        "Prompt fuer einen AI-Assistenten um. Mache aus dem Gesprochenen eine "
        "praezise Anfrage mit: klarer Aufgabenstellung, spezifischen "
        "Anforderungen, und optional Kontext oder Beispiel. Behalte die "
        "Originalsprache bei. Gib NUR den Prompt zurueck, keine Erklaerung.\n\n"
        "Gesprochen: {text}\n\nPrompt:"
    ),
}


class TextProcessor:
    def __init__(self, mode: str = "off", model: str = DEFAULT_MODEL):
        self.mode = mode
        self.model = model

    def process(self, text: str) -> str:
        """Verarbeitet den Text gemaess Mode. Fallback auf Raw bei Fehler."""
        if self.mode == "off" or not text:
            return text
        prompt_template = PROMPTS.get(self.mode)
        if not prompt_template:
            return text

        prompt = prompt_template.format(text=text)
        try:
            result = self._query_ollama(prompt)
            if result:
                log.info("Post-processing '%s': %d -> %d Zeichen",
                         self.mode, len(text), len(result))
                return result
            log.warning("Ollama lieferte leeren Text, fallback auf raw")
            return text
        except Exception as e:
            log.error("Ollama Post-processing fehlgeschlagen: %s", e)
            return text

    def _query_ollama(self, prompt: str, timeout: int = 60) -> str:
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 2048},
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("response", "").strip()


# --- Ollama Status ---

def check_ollama() -> tuple[bool, list[str]]:
    """Prueft ob Ollama laeuft und gibt verfuegbare Modelle zurueck.

    Returns:
        (is_running, list_of_model_names)
    """
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m["name"] for m in data.get("models", [])]
            return True, models
    except Exception:
        return False, []


def get_ollama_state(required_model: str = DEFAULT_MODEL) -> str:
    """Returns state: 'ready', 'no_model', oder 'not_installed'."""
    running, models = check_ollama()
    if not running:
        return "not_installed"
    if required_model not in models:
        return "no_model"
    return "ready"


# --- Ollama Installer ---

def install_ollama(progress_callback=None) -> bool:
    """Laedt den Ollama Windows-Installer und startet ihn.

    Der User sieht den normalen Installer-Wizard (kein silent install).
    progress_callback(completed_bytes, total_bytes, status_text) waehrend Download.
    Wartet danach bis zu 120s bis die Ollama-API erreichbar ist.
    """
    installer_path = os.path.join(tempfile.gettempdir(), "OllamaSetup.exe")

    # Phase 1: Download
    log.info("Lade Ollama-Installer von %s", OLLAMA_INSTALLER_URL)
    try:
        _download_with_progress(OLLAMA_INSTALLER_URL, installer_path, progress_callback)
    except Exception as e:
        log.error("Ollama-Download fehlgeschlagen: %s", e)
        raise RuntimeError(f"Download fehlgeschlagen: {e}")

    # Phase 2: Installer starten (zeigt Wizard fuer User)
    if progress_callback:
        progress_callback(0, 0, "Warte auf Installer...")
    log.info("Starte Ollama-Installer: %s", installer_path)
    try:
        subprocess.Popen([installer_path])
    except Exception as e:
        log.error("Installer-Start fehlgeschlagen: %s", e)
        raise RuntimeError(f"Installer-Start fehlgeschlagen: {e}")

    # Phase 3: Warte bis API erreichbar
    if progress_callback:
        progress_callback(0, 0, "Warte auf Ollama-Start...")
    log.info("Warte auf Ollama-API...")
    deadline = time.time() + 180  # 3 Minuten fuer langsame Installationen
    while time.time() < deadline:
        running, _ = check_ollama()
        if running:
            log.info("Ollama ist bereit")
            try:
                os.remove(installer_path)
            except OSError:
                pass
            return True
        time.sleep(3)

    raise RuntimeError("Ollama-Installation Timeout (3 Minuten). Bitte manuell starten.")


def _download_with_progress(url, dest, progress_callback):
    """Einfacher Download mit optional progress_callback."""
    def reporthook(block, block_size, total_size):
        if progress_callback and total_size > 0:
            downloaded = min(block * block_size, total_size)
            progress_callback(downloaded, total_size, "Lade Ollama...")

    urllib.request.urlretrieve(url, dest, reporthook)


# --- Ollama Model Pull ---

def pull_model(model_name: str, progress_callback=None) -> bool:
    """Laedt ein Ollama-Modell via HTTP Streaming API.

    progress_callback(completed_bytes, total_bytes, status_text)
    Nutzt POST /api/pull mit stream=true fuer Live-Progress.
    """
    log.info("Pull Ollama-Modell: %s", model_name)
    payload = json.dumps({"model": model_name, "stream": True}).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/pull",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            for line in resp:
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue

                status = msg.get("status", "")
                total = int(msg.get("total", 0))
                completed = int(msg.get("completed", 0))

                if progress_callback:
                    progress_callback(completed, total, status)

                if msg.get("error"):
                    raise RuntimeError(msg["error"])

                if "success" in status.lower():
                    log.info("Modell '%s' erfolgreich geladen", model_name)
                    return True
        return True
    except Exception as e:
        log.error("Model-Pull fehlgeschlagen: %s", e)
        raise
