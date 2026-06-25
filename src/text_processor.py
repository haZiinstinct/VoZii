"""Text Post-Processing via Ollama (lokal) + Ollama Install/Pull/Start Management."""

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request

log = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434"
OLLAMA_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
DEFAULT_MODEL = "qwen2.5:3b"

# 3-Stufen-Auswahl fuers Post-Processing: stabile ID -> (Ollama-Tag, Groesse).
# Die Anzeige-Namen kommen aus der i18n (aimodel.fast/balanced/best).
# Bewusst Modelle OHNE Thinking-Mode (sauberer, schneller Output).
OLLAMA_TIERS = {
    "fast": ("llama3.2:1b", "~1,3 GB"),
    "balanced": ("qwen2.5:3b", "~2 GB"),
    "best": ("gemma3:4b", "~3 GB"),
}


def tier_for_model(tag: str) -> str:
    """Stufen-ID fuer einen Modell-Tag (Default: balanced)."""
    for tier_id, (t, _) in OLLAMA_TIERS.items():
        if t == tag:
            return tier_id
    return "balanced"


def size_label(tag: str) -> str:
    """Ungefaehre Download-Groesse fuer einen Modell-Tag."""
    for _, (t, size) in OLLAMA_TIERS.items():
        if t == tag:
            return size
    return "~2 GB"


# System-Prompt + Few-Shot-Beispiele je Modus. Few-Shot macht kleine Modelle
# deutlich zuverlaessiger und haelt sie vom Vorreden ab.
_SMART_SYSTEM = (
    "Du bist ein Textbereiniger fuer eine Voice-to-Text-App. Verbessere den "
    "gesprochenen Text:\n"
    "1. Entferne Fuellwoerter (aehm, also, halt, ja, ne, sozusagen).\n"
    "2. Korrigiere Grammatik, Interpunktion und offensichtliche Versprecher.\n"
    "3. Behalte die Sprache des Originals bei.\n"
    "4. Voice-Commands befolgen und aus dem Text entfernen: 'als Liste' -> "
    "Markdown-Liste mit '-'; 'als Email' -> formeller Email-Stil; 'als Code' -> "
    "Codeblock mit ```; 'Ueberschrift'/'als Titel' -> '# '; 'neuer Absatz' -> "
    "Absatzumbruch.\n"
    "5. Ohne Command passend formatieren: Aufzaehlung -> Liste, mehrere Gedanken "
    "-> Absaetze, sonst ein sauberer Satz.\n"
    "Gib AUSSCHLIESSLICH den fertigen Text aus - keine Erklaerung, keine "
    "Anfuehrungszeichen, kein Vorwort."
)
_SMART_FEWSHOT = [
    ("aehm ich wollte halt sagen dass das tool wirklich super funktioniert",
     "Ich wollte sagen, dass das Tool wirklich super funktioniert."),
    ("ich brauche folgende zutaten als liste mehl zucker butter und eier",
     "- Mehl\n- Zucker\n- Butter\n- Eier"),
]

_PROMPT_SYSTEM = (
    "Wandle gesprochenen Text in einen praezisen, gut strukturierten Prompt "
    "fuer einen KI-Assistenten um: klare Aufgabe, konkrete Anforderungen, "
    "optional Kontext. Behalte die Sprache des Originals bei. Gib "
    "AUSSCHLIESSLICH den Prompt aus - keine Erklaerung, kein Vorwort."
)
_PROMPT_FEWSHOT = [
    ("schreib ne email an meinen chef dass ich morgen nicht kann weil ich zum arzt muss",
     "Schreibe eine hoefliche, formelle E-Mail an meinen Vorgesetzten. Inhalt: "
     "Ich kann morgen nicht arbeiten, da ich einen Arzttermin habe. Bitte um "
     "Verstaendnis und biete an, dringende Aufgaben vorab zu erledigen. Ton: "
     "professionell und knapp."),
]

# Modus -> (System-Prompt, Few-Shot, Temperatur)
PROMPTS = {
    "smart": (_SMART_SYSTEM, _SMART_FEWSHOT, 0.2),
    "prompt": (_PROMPT_SYSTEM, _PROMPT_FEWSHOT, 0.4),
}

_PREAMBLE_RE = re.compile(
    r"^(hier ist[^\n:]*:|klar[,!.]?\s+|gerne[,!.]?\s+|sicher[,!.]?\s+|natuerlich[,!.]?\s+)",
    re.IGNORECASE,
)


def _clean_response(text: str) -> str:
    """Entfernt Vorworte, umschliessende Quotes und durchgesickerte Reasoning-Bloecke."""
    if not text:
        return ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    text = _PREAMBLE_RE.sub("", text).strip()
    if len(text) >= 2 and text[0] in "\"'„“" and text[-1] in "\"'”“":
        text = text[1:-1].strip()
    return text


class TextProcessor:
    def __init__(self, mode: str = "off", model: str = DEFAULT_MODEL):
        self.mode = mode
        self.model = model

    def process(self, text: str) -> str:
        """Verarbeitet den Text gemaess Mode. Fallback auf Raw bei Fehler."""
        if self.mode == "off" or not text:
            return text
        spec = PROMPTS.get(self.mode)
        if not spec:
            return text
        system, fewshot, temperature = spec
        try:
            result = _clean_response(self._chat(system, fewshot, text, temperature))
            if result:
                log.info("Post-processing '%s': %d -> %d Zeichen",
                         self.mode, len(text), len(result))
                return result
            log.warning("Ollama lieferte leeren Text, fallback auf raw")
            return text
        except Exception as e:
            log.error("Ollama Post-processing fehlgeschlagen: %s", e)
            return text

    def _chat(self, system: str, fewshot, text: str, temperature: float,
              timeout: int = 60) -> str:
        messages = [{"role": "system", "content": system}]
        for user_msg, assistant_msg in fewshot:
            messages.append({"role": "user", "content": user_msg})
            messages.append({"role": "assistant", "content": assistant_msg})
        messages.append({"role": "user", "content": text})

        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,  # Reasoning-Modelle sollen nicht ihre Gedanken ausgeben
            "options": {"temperature": temperature, "num_predict": 1024},
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("message", {}).get("content", "").strip()


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

def _verify_authenticode(path: str) -> bool:
    """Prueft Code-Signatur des Installers: Status Valid + Aussteller Ollama.

    Schutz davor, eine manipulierte Exe auszufuehren (der Installer-Download
    hat keine veroeffentlichten Checksummen, die Signatur ist die Verifikation).
    """
    # Single-Quotes im Pfad escapen (PowerShell: '' = literales ')
    safe_path = path.replace("'", "''")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"$s = Get-AuthenticodeSignature -LiteralPath '{safe_path}'; "
             "Write-Output $s.Status; Write-Output $s.SignerCertificate.Subject"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
        if len(lines) < 2 or lines[0] != "Valid":
            log.error("Installer-Signatur ungueltig: %s", lines[:1] or "keine Ausgabe")
            return False
        if "ollama" not in lines[1].lower():
            log.error("Installer-Signatur von unerwartetem Aussteller: %s", lines[1])
            return False
        return True
    except Exception:
        log.exception("Signaturpruefung fehlgeschlagen")
        return False


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
        raise RuntimeError(f"Download fehlgeschlagen: {e}") from e

    # Phase 1b: Signatur pruefen BEVOR irgendwas ausgefuehrt wird
    if progress_callback:
        progress_callback(0, 0, "Pruefe Signatur...", 0)
    if not _verify_authenticode(installer_path):
        try: os.remove(installer_path)
        except OSError: pass
        raise RuntimeError(
            "Signaturpruefung des Ollama-Installers fehlgeschlagen — Download verworfen.\n"
            "Bitte erneut versuchen oder Ollama manuell von ollama.com installieren."
        )

    # Phase 2: Installer starten (User sieht Wizard)
    if progress_callback:
        progress_callback(0, 0, "Installer gestartet, bitte durchklicken...", 0)
    log.info("Starte Ollama-Installer: %s", installer_path)
    try:
        subprocess.Popen([installer_path])
    except Exception as e:
        log.error("Installer-Start fehlgeschlagen: %s", e)
        raise RuntimeError(f"Installer-Start fehlgeschlagen: {e}") from e

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
