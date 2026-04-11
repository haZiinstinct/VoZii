"""Text Post-Processing via Ollama (lokal)."""

import json
import logging
import urllib.request

log = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434"
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
