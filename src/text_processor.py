"""Optionale Korrektur des Diktats via Ollama (lokal).

Bewusst minimal: ein Modus (Korrektur), ein Modell (das kleinste). Fehlt
Ollama, installiert VoZii es selbst (signaturgeprueft), startet es und laedt
das Modell.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request

from src.i18n import t
from src.winutil import system32

log = logging.getLogger(__name__)

OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
# CN des Code-Signing-Zertifikats von Ollama (abgelesen per
# Get-AuthenticodeSignature an ollama.exe, Oktober 2026). Exakter Vergleich —
# ein Teilstring "ollama" wuerde auch fremde Zertifikate durchlassen.
OLLAMA_SIGNER_CN = "Ollama Inc."
# Kleinstes brauchbares Modell ohne Thinking-Mode: schnell, ~1,3 GB
MODEL = "llama3.2:1b"
MODES = ("off", "correct")

# Loopback-Opener ohne System-Proxy (Firmen-/VPN-Umgebungen)
_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_ORIG_URLOPEN = urllib.request.urlopen


def _local_urlopen(req, timeout: float):
    if urllib.request.urlopen is not _ORIG_URLOPEN:
        return urllib.request.urlopen(req, timeout=timeout)
    return _LOCAL_OPENER.open(req, timeout=timeout)


# Nur korrigieren: keine Voice-Commands, kein Umformatieren. Ein Few-Shot-
# Beispiel haelt kleine Modelle vom Vorreden ab.
_CORRECT_SYSTEM = (
    "Du korrigierst diktierten Text aus einer Voice-to-Text-App:\n"
    "1. Korrigiere Rechtschreibung, Grammatik, Interpunktion und offensichtliche "
    "Versprecher.\n"
    "2. Entferne Füllwörter (ähm, äh, also, halt, sozusagen).\n"
    "3. Ändere sonst nichts: kein Umformulieren, kein Umformatieren, keine "
    "Übersetzung.\n"
    "Gib AUSSCHLIESSLICH den korrigierten Text aus — keine Erklärung, keine "
    "Anführungszeichen, kein Vorwort."
)
_CORRECT_FEWSHOT = [
    ("ähm ich wollte halt sagen das das tool wirklich super funktioniert",
     "Ich wollte sagen, dass das Tool wirklich super funktioniert."),
]

# Fuer alle anderen Diktat-Sprachen: englische Anweisungen + Beispiel.
# Deutsche Few-Shots zogen kleine Modelle sonst ins Deutsche.
_CORRECT_SYSTEM_EN = (
    "You correct dictated text from a voice-to-text app:\n"
    "1. Fix spelling, grammar, punctuation and obvious slips of the tongue.\n"
    "2. Remove filler words (um, uh, like, you know, basically).\n"
    "3. Change nothing else: no rewording, no reformatting, never translate.\n"
    "Output ONLY the corrected text - no explanation, no quotes, no preamble."
)
_CORRECT_FEWSHOT_EN = [
    ("um so i wanted to say that the tool like really works great",
     "I wanted to say that the tool really works great."),
]

# Prompt-Sprache -> (System-Prompt, Few-Shot)
PROMPTS = {
    "de": (_CORRECT_SYSTEM, _CORRECT_FEWSHOT),
    "en": (_CORRECT_SYSTEM_EN, _CORRECT_FEWSHOT_EN),
}


def prompt_language(dictation_lang: str, ui_lang: str) -> str:
    """Prompt-Satz waehlen: Diktat-Sprache, bei 'auto' die UI-Sprache.
    Deutsch hat eigene Prompts, alles andere nimmt die englischen."""
    lang = ui_lang if dictation_lang in (None, "", "auto") else dictation_lang
    return "de" if lang == "de" else "en"


# Nur Vorworte mit Doppelpunkt fuer Englisch — "Sure, ..." kann echter
# Diktat-Inhalt sein
_PREAMBLE_RE = re.compile(
    r"^(hier ist[^\n:]*:|klar[,!.]?\s+|gerne[,!.]?\s+|sicher[,!.]?\s+|nat(?:ü|ue)rlich[,!.]?\s+"
    r"|here is[^\n:]*:|here's[^\n:]*:)",
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
    def __init__(self, mode: str = "off", prompt_lang: str = "de", model: str = MODEL):
        self.mode = mode if mode in MODES else "off"
        self.model = model
        self.prompt_lang = prompt_lang if prompt_lang in PROMPTS else "en"

    def process(self, text: str) -> str:
        """Korrigiert den Text. Fallback auf den Rohtext bei jedem Fehler."""
        if self.mode == "off" or not text:
            return text
        system, fewshot = PROMPTS[self.prompt_lang]
        try:
            result = _clean_response(self._chat(system, fewshot, text))
            if not result:
                log.warning("Ollama lieferte leeren Text, fallback auf raw")
                return text
            # Plausibilitaets-Guard: wenn das 1B-Modell ein langes Diktat stark
            # abschneidet oder verweigert, lieber den vollstaendigen Rohtext retten
            if len(text) >= 40 and len(result) < len(text) * 0.35:
                log.warning("Ollama-Antwort verdaechtig kurz (%d -> %d Zeichen) — "
                            "nutze Rohtext", len(text), len(result))
                return text
            log.info("Korrektur: %d -> %d Zeichen", len(text), len(result))
            return result
        except Exception as e:
            log.error("Ollama-Korrektur fehlgeschlagen: %s", e)
            return text

    def _chat(self, system: str, fewshot, text: str, timeout: int = 60) -> str:
        messages = [{"role": "system", "content": system}]
        for user_msg, assistant_msg in fewshot:
            messages.append({"role": "user", "content": user_msg})
            messages.append({"role": "assistant", "content": assistant_msg})
        messages.append({"role": "user", "content": text})

        num_predict = max(1024, int(len(text) * 0.6) + 256)
        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": 0.1, "num_predict": num_predict},
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _local_urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("message", {}).get("content", "").strip()


# --- Ollama Status / Detection ---

def check_ollama() -> tuple[bool, list[str]]:
    """Prueft ob Ollama-API erreichbar ist. Returns (is_running, list_of_model_names)."""
    try:
        with _local_urlopen(f"{OLLAMA_URL}/api/tags", timeout=2) as resp:
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
    # 1. Standard-Installationsorte zuerst: das Ergebnis wird beim App-Start
    # automatisch ausgefuehrt (start_ollama_if_needed), und PATH schliesst
    # unter Windows auch das aktuelle Verzeichnis ein
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.path.join(local_appdata, "Programs", "Ollama", "ollama app.exe"),
        os.path.join(local_appdata, "Programs", "Ollama", "ollama.exe"),
        r"C:\Program Files\Ollama\ollama.exe",
    ]
    for p in candidates:
        if p and os.path.isfile(p):
            return p

    # 2. PATH als Fallback (eigener Installationsort)
    return shutil.which("ollama")


def get_ollama_state(required_model: str = MODEL) -> str:
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

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        running, _ = check_ollama()
        if running:
            log.info("Ollama gestartet, API bereit")
            return True
        time.sleep(0.5)
    log.warning("Ollama-Start Timeout nach %ds", timeout)
    return False


def start_ollama_if_needed() -> bool:
    """Startet ein installiertes, aber nicht laufendes Ollama (best-effort,
    fuer den Tray-Betrieb). Installiert nie ungefragt."""
    running, models = check_ollama()
    if not running:
        path = is_ollama_installed()
        if not path:
            log.warning("Korrektur aktiv, aber Ollama nicht installiert")
            return False
        if not start_ollama(path):
            return False
        running, models = check_ollama()
    if MODEL not in models:
        # z. B. nach der Migration von qwen2.5:3b: jede Korrektur faellt
        # sonst kommentarlos auf den Rohtext zurueck
        log.warning("Korrektur aktiv, aber Modell %s fehlt — in den "
                    "Einstellungen 'Korrektur' anklicken", MODEL)
        return False
    return True


# --- Ollama Installer mit Cancel + Speed ---

def _subject_field(subject: str, name: str) -> str | None:
    """Liest ein RDN-Feld (z. B. CN) aus einem X.500-Subject; Werte mit Komma
    stehen dort in Anfuehrungszeichen."""
    m = re.search(rf'(?:^|,)\s*{name}=("([^"]*)"|[^,]*)', subject)
    if not m:
        return None
    return (m.group(2) if m.group(2) is not None else m.group(1)).strip()


def _verify_authenticode(path: str) -> bool:
    """Prueft Code-Signatur des Installers: Status Valid + Aussteller Ollama.

    Schutz davor, eine manipulierte Exe auszufuehren (der Installer-Download
    hat keine veroeffentlichten Checksummen, die Signatur ist die Verifikation).
    """
    # Single-Quotes im Pfad escapen (PowerShell: '' = literales ')
    safe_path = path.replace("'", "''")
    try:
        result = subprocess.run(
            [system32("WindowsPowerShell", "v1.0", "powershell.exe"), "-NoProfile", "-Command",
             f"$s = Get-AuthenticodeSignature -LiteralPath '{safe_path}'; "
             "Write-Output $s.Status; Write-Output $s.SignerCertificate.Subject"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
        if len(lines) < 2 or lines[0] != "Valid":
            log.error("Installer-Signatur ungueltig: %s", lines[:1] or "keine Ausgabe")
            return False
        if _subject_field(lines[1], "CN") != OLLAMA_SIGNER_CN:
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
    # Eigenes Temp-Unterverzeichnis statt festem Pfad %TEMP%\OllamaSetup.exe
    # (Audit S5: verhindert Pfad-Kollisionen/Manipulation zwischen Pruefung & Start)
    tmp_dir = tempfile.mkdtemp(prefix="vozii_ollama_")
    installer_path = os.path.join(tmp_dir, "OllamaSetup.exe")

    try:
        # Phase 1: Chunked Download
        log.info("Lade Ollama-Installer von %s", OLLAMA_INSTALLER_URL)
        try:
            _download_ollama_installer(
                OLLAMA_INSTALLER_URL, installer_path, progress_callback, cancel_event,
            )
        except InterruptedError:
            raise
        except Exception as e:
            log.error("Ollama-Download fehlgeschlagen: %s", e)
            raise RuntimeError(t("err.ollama_download", error=e)) from e

        # Phase 1b: Signatur pruefen BEVOR irgendwas ausgefuehrt wird
        if progress_callback:
            progress_callback(0, 0, t("ollama.verify_sig"), 0)
        if not _verify_authenticode(installer_path):
            raise RuntimeError(t("err.ollama_signature"))

        # Phase 2: Installer starten (User sieht Wizard)
        if progress_callback:
            progress_callback(0, 0, t("ollama.installer_started"), 0)
        log.info("Starte Ollama-Installer: %s", installer_path)
        try:
            subprocess.Popen([installer_path])
        except Exception as e:
            log.error("Installer-Start fehlgeschlagen: %s", e)
            raise RuntimeError(t("err.installer_start", error=e)) from e

        # Phase 3: Warte bis API erreichbar (mit Cancel)
        if progress_callback:
            progress_callback(0, 0, t("ollama.waiting"), 0)
        log.info("Warte auf Ollama-API...")
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Abgebrochen")
            running, _ = check_ollama()
            if running:
                log.info("Ollama ist bereit")
                return True
            time.sleep(1.5)

        raise RuntimeError(t("err.ollama_timeout"))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _download_ollama_installer(url, dest, progress_callback, cancel_event):
    """Chunked Download mit Cancel und Speed-Tracking."""
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        last_update = time.monotonic()
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

                now = time.monotonic()
                if now - last_update >= 0.2:
                    delta_bytes = downloaded - last_bytes
                    delta_time = now - last_update
                    speed = delta_bytes / delta_time if delta_time > 0 else 0
                    if progress_callback:
                        progress_callback(downloaded, total, t("ollama.dl_installer"), speed)
                    last_update = now
                    last_bytes = downloaded

        # Final update
        if progress_callback:
            progress_callback(downloaded, total, t("ollama.dl_installer"), 0)


def ensure_ready(progress_callback=None, cancel_event=None, model: str = MODEL) -> bool:
    """Bringt die Korrektur in einem Rutsch zum Laufen: Ollama installieren
    (falls fehlt), starten (falls aus), Modell laden (falls fehlt).

    progress_callback(completed, total, status_text, speed_bps)
    Raises RuntimeError/InterruptedError wie die Einzelschritte."""
    state = get_ollama_state(model)
    if state == "not_installed":
        install_ollama(progress_callback, cancel_event)  # startet Ollama mit
        state = get_ollama_state(model)
    if state == "installed_not_running":
        if progress_callback:
            progress_callback(0, 0, t("ollama.status.starting"), 0)
        path = is_ollama_installed()
        if not path:
            raise RuntimeError(t("ollama.not_found"))
        if not start_ollama(path):
            raise RuntimeError(t("err.ollama_start_timeout"))
        state = get_ollama_state(model)
    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Abgebrochen")
    if state == "no_model":
        pull_model(model, progress_callback, cancel_event)
    return True


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

    last_update = time.monotonic()
    last_completed = 0
    last_total = 0

    try:
        # Grosszuegiger Read-Timeout: Ollama pausiert den Stream beim
        # Verifizieren grosser Layer-Digests fuer >30 s auf langsamen Platten
        with _local_urlopen(req, timeout=120) as resp:
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
                # Layer-Wechsel: completed startet wieder bei 0
                if total != last_total or completed < last_completed:
                    last_completed = completed
                    last_total = total

                now = time.monotonic()
                delta_t = now - last_update
                if delta_t >= 0.2:
                    delta_bytes = max(0, completed - last_completed)
                    speed = delta_bytes / delta_t if delta_t > 0 else 0
                    if progress_callback:
                        # Ollamas eigener Status ("pulling manifest") ist
                        # englischer Jargon — einheitlicher Text statt dessen
                        progress_callback(completed, total, t("ollama.dl_model"), speed)
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
