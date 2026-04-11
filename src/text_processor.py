"""Text Post-Processing via Ollama (lokal) + Ollama Install/Pull/Start Management."""

import json
import logging
import os
import shutil
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


# --- Ollama Status / Detection ---

def check_ollama() -> tuple[bool, list[str]]:
    """Prueft ob Ollama-API erreichbar ist. Returns (is_running, list_of_model_names)."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m["name"] for m in data.get("models", [])]
            return True, models
    except Exception:
        return False, []


def is_ollama_installed() -> str | None:
    """Prueft ob Ollama installiert ist (auch wenn nicht laeuft).

    Returns:
        Pfad zur ollama executable, oder None wenn nicht gefunden.
    """
    # 1. PATH check
    path = shutil.which("ollama")
    if path:
        return path

    # 2. Standard Windows Install-Locations
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.path.join(local_appdata, "Programs", "Ollama", "ollama app.exe"),
        os.path.join(local_appdata, "Programs", "Ollama", "ollama.exe"),
        r"C:\Program Files\Ollama\ollama.exe",
    ]
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return None


def get_ollama_state(required_model: str = DEFAULT_MODEL) -> str:
    """Returns state:
    - 'ready': Ollama laeuft, Modell da
    - 'no_model': Ollama laeuft, Modell fehlt
    - 'installed_not_running': Ollama installiert, nicht gestartet
    - 'not_installed': Ollama nicht installiert
    """
    running, models = check_ollama()
    if running:
        if required_model in models:
            return "ready"
        return "no_model"
    if is_ollama_installed():
        return "installed_not_running"
    return "not_installed"


def stop_ollama() -> bool:
    """Beendet Ollama via taskkill (GUI-App + CLI serve).

    Returns True wenn mindestens ein Prozess beendet wurde.
    """
    success = False
    for proc_name in ("ollama app.exe", "ollama.exe"):
        try:
            result = subprocess.run(
                ["taskkill", "/f", "/im", proc_name],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode == 0:
                success = True
                log.info("Beendet: %s", proc_name)
        except Exception as e:
            log.debug("Konnte %s nicht beenden: %s", proc_name, e)
    return success


def start_ollama(ollama_path: str, timeout: int = 30) -> bool:
    """Startet Ollama (bevorzugt GUI app, fallback auf 'ollama serve').

    Returns True wenn die API danach erreichbar ist.
    """
    log.info("Starte Ollama: %s", ollama_path)
    try:
        if "ollama app.exe" in ollama_path.lower():
            subprocess.Popen([ollama_path])
        else:
            subprocess.Popen(
                [ollama_path, "serve"],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
    except Exception as e:
        log.error("Ollama start failed: %s", e)
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        running, _ = check_ollama()
        if running:
            log.info("Ollama gestartet, API bereit")
            return True
        time.sleep(1)
    log.warning("Ollama-Start Timeout nach %ds", timeout)
    return False


# --- Ollama Installer mit Cancel + Speed ---

def install_ollama(progress_callback=None, cancel_event=None) -> bool:
    """Laedt den Ollama Windows-Installer und startet ihn.

    progress_callback(completed, total, status_text, speed_bps)
    cancel_event: threading.Event, bei is_set() wird InterruptedError geworfen.
    """
    installer_path = os.path.join(tempfile.gettempdir(), "OllamaSetup.exe")

    # Phase 1: Chunked Download
    log.info("Lade Ollama-Installer von %s", OLLAMA_INSTALLER_URL)
    try:
        _download_ollama_installer(
            OLLAMA_INSTALLER_URL, installer_path, progress_callback, cancel_event,
        )
    except InterruptedError:
        if os.path.exists(installer_path):
            try: os.remove(installer_path)
            except OSError: pass
        raise
    except Exception as e:
        log.error("Ollama-Download fehlgeschlagen: %s", e)
        if os.path.exists(installer_path):
            try: os.remove(installer_path)
            except OSError: pass
        raise RuntimeError(f"Download fehlgeschlagen: {e}")

    # Phase 2: Installer starten (User sieht Wizard)
    if progress_callback:
        progress_callback(0, 0, "Installer gestartet, bitte durchklicken...", 0)
    log.info("Starte Ollama-Installer: %s", installer_path)
    try:
        subprocess.Popen([installer_path])
    except Exception as e:
        log.error("Installer-Start fehlgeschlagen: %s", e)
        raise RuntimeError(f"Installer-Start fehlgeschlagen: {e}")

    # Phase 3: Warte bis API erreichbar (mit Cancel)
    if progress_callback:
        progress_callback(0, 0, "Warte auf Ollama-Start...", 0)
    log.info("Warte auf Ollama-API...")
    deadline = time.time() + 180
    while time.time() < deadline:
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Abgebrochen")
        running, _ = check_ollama()
        if running:
            log.info("Ollama ist bereit")
            try: os.remove(installer_path)
            except OSError: pass
            return True
        time.sleep(2)

    raise RuntimeError("Ollama-Installation Timeout (3 Minuten)")


def _download_ollama_installer(url, dest, progress_callback, cancel_event):
    """Chunked Download mit Cancel und Speed-Tracking."""
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        start_time = time.time()
        last_update = start_time
        last_bytes = 0

        with open(dest, "wb") as f:
            while True:
                if cancel_event and cancel_event.is_set():
                    raise InterruptedError("Abgebrochen")
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)

                now = time.time()
                if now - last_update >= 0.2:
                    delta_bytes = downloaded - last_bytes
                    delta_time = now - last_update
                    speed = delta_bytes / delta_time if delta_time > 0 else 0
                    if progress_callback:
                        progress_callback(downloaded, total, "Lade Installer", speed)
                    last_update = now
                    last_bytes = downloaded

        # Final update
        if progress_callback:
            progress_callback(downloaded, total, "Installer geladen", 0)


# --- Ollama Model Pull mit Cancel + Speed ---

def pull_model(model_name: str, progress_callback=None, cancel_event=None) -> bool:
    """Pull Ollama-Modell mit Cancel-Support und Speed-Tracking.

    progress_callback(completed, total, status_text, speed_bps)
    """
    log.info("Pull Ollama-Modell: %s", model_name)
    payload = json.dumps({"model": model_name, "stream": True}).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/pull",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    last_update = time.time()
    last_completed = 0

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            for line in resp:
                if cancel_event and cancel_event.is_set():
                    raise InterruptedError("Abgebrochen")
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue

                status = msg.get("status", "")
                total = int(msg.get("total", 0))
                completed = int(msg.get("completed", 0))

                now = time.time()
                delta_t = now - last_update
                if delta_t >= 0.2:
                    delta_bytes = completed - last_completed
                    speed = delta_bytes / delta_t if delta_t > 0 else 0
                    if progress_callback:
                        progress_callback(completed, total, status, speed)
                    last_update = now
                    last_completed = completed

                if msg.get("error"):
                    raise RuntimeError(msg["error"])

                if "success" in status.lower():
                    log.info("Modell '%s' erfolgreich geladen", model_name)
                    return True
        return True
    except InterruptedError:
        raise
    except Exception as e:
        log.error("Model-Pull fehlgeschlagen: %s", e)
        raise
