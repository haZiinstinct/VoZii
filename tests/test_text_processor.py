"""Text-Post-Processing: Tier-Helfer, Output-Cleaning, Chat-Request-Aufbau."""

import json

from src import text_processor as tp
from src.text_processor import (
    OLLAMA_TIERS,
    TextProcessor,
    _clean_response,
    size_label,
    tier_for_model,
)


def test_tier_for_model():
    # Stabile IDs (Anzeige-Namen kommen aus der i18n, nicht aus tier_for_model)
    assert tier_for_model("llama3.2:1b") == "fast"
    assert tier_for_model("qwen2.5:3b") == "balanced"
    assert tier_for_model("gemma3:4b") == "best"
    assert tier_for_model("unbekannt:9b") == "balanced"  # Fallback


def test_size_label():
    assert size_label("qwen2.5:3b") == "~2 GB"
    assert size_label("gemma3:4b") == "~3 GB"
    assert size_label("unbekannt") == "~2 GB"


def test_tiers_consistent():
    # Jede Stufe hat Tag + Groesse; Default-Tag ist in den Tiers
    assert all(len(v) == 2 for v in OLLAMA_TIERS.values())
    assert tp.DEFAULT_MODEL in {tag for tag, _ in OLLAMA_TIERS.values()}


def test_clean_response_strips_preamble():
    assert _clean_response("Hier ist der Text: Hallo Welt") == "Hallo Welt"
    assert _clean_response("Klar, Hallo Welt") == "Hallo Welt"
    assert _clean_response("Gerne! Hallo Welt") == "Hallo Welt"


def test_clean_response_strips_quotes():
    assert _clean_response('"Hallo Welt"') == "Hallo Welt"
    assert _clean_response("„Hallo Welt“") == "Hallo Welt"


def test_clean_response_strips_think_block():
    assert _clean_response("<think>ueberlege...</think>Endergebnis") == "Endergebnis"
    assert _clean_response("<THINK>x</THINK>\nText") == "Text"


def test_clean_response_keeps_normal_text():
    assert _clean_response("Ein ganz normaler Satz.") == "Ein ganz normaler Satz."
    assert _clean_response("") == ""


def test_chat_request_structure(monkeypatch):
    """process() im Smart-Modus baut den Chat-Request korrekt (System + Few-Shot + User)."""
    captured = {}

    class FakeResp:
        def __init__(self, payload):
            self._b = json.dumps(payload).encode("utf-8")
        def read(self):
            return self._b
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResp({"message": {"content": "  bereinigt  "}})

    monkeypatch.setattr(tp.urllib.request, "urlopen", fake_urlopen)

    out = TextProcessor(mode="smart", model="qwen2.5:3b").process("aehm hallo")
    assert out == "bereinigt"  # getrimmt
    assert captured["url"].endswith("/api/chat")
    body = captured["body"]
    assert body["model"] == "qwen2.5:3b"
    assert body["think"] is False
    assert body["stream"] is False
    roles = [m["role"] for m in body["messages"]]
    assert roles[0] == "system"
    assert roles[-1] == "user"
    assert body["messages"][-1]["content"] == "aehm hallo"
    assert "assistant" in roles  # Few-Shot vorhanden


def test_process_off_and_empty():
    assert TextProcessor(mode="off").process("x") == "x"
    assert TextProcessor(mode="smart").process("") == ""


def test_process_fallback_on_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("Ollama weg")
    monkeypatch.setattr(tp.urllib.request, "urlopen", boom)
    assert TextProcessor(mode="smart").process("mein text") == "mein text"


# --- Authenticode-Pruefung des Ollama-Installers (C2) ---

_REAL_SUBJECT = ("CN=Ollama Inc., O=Ollama Inc., L=Toronto, S=Ontario, C=CA, "
                 "SERIALNUMBER=2713355, OID.2.5.4.15=Private Organization")


def _fake_signature(monkeypatch, stdout):
    calls = []

    class Result:
        returncode = 0

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        r = Result()
        r.stdout = stdout
        return r

    monkeypatch.setattr(tp.subprocess, "run", fake_run)
    return calls


def test_authenticode_gueltig(monkeypatch):
    calls = _fake_signature(monkeypatch, f"Valid\n{_REAL_SUBJECT}\n")
    assert tp._verify_authenticode(r"C:\x\OllamaSetup.exe") is True
    # PowerShell mit absolutem Pfad, nicht ueber PATH (C1)
    assert calls[0][0].lower().endswith(r"\system32\windowspowershell\v1.0\powershell.exe")


def test_authenticode_falscher_cn_trotz_teilstring(monkeypatch):
    for subject in ("CN=Not Ollama Inc., O=Evil", "CN=ollama-fake, O=Ollama Inc.",
                    "CN=Evil Corp, OU=ollama"):
        _fake_signature(monkeypatch, f"Valid\n{subject}\n")
        assert tp._verify_authenticode("x.exe") is False, subject


def test_authenticode_status_nicht_valid(monkeypatch):
    _fake_signature(monkeypatch, f"HashMismatch\n{_REAL_SUBJECT}\n")
    assert tp._verify_authenticode("x.exe") is False
    _fake_signature(monkeypatch, "")
    assert tp._verify_authenticode("x.exe") is False


def test_subject_field_mit_anfuehrungszeichen():
    assert tp._subject_field('CN="Ollama, Inc.", O=X', "CN") == "Ollama, Inc."
    assert tp._subject_field("O=X", "CN") is None


def test_stop_ollama_nutzt_absoluten_taskkill_pfad(monkeypatch):
    calls = _fake_signature(monkeypatch, "")
    tp.stop_ollama()
    assert calls and all(c[0].lower().endswith(r"\system32\taskkill.exe") for c in calls)


def test_prompt_sprache_nach_diktat_und_ui_sprache():
    assert tp.prompt_language("de", "en") == "de"
    assert tp.prompt_language("fr", "de") == "en"
    assert tp.prompt_language("auto", "de") == "de"
    assert tp.prompt_language("auto", "ja") == "en"


def test_englische_prompts_fuer_andere_sprachen(monkeypatch):
    captured = {}

    def fake_chat(self, system, fewshot, text, temperature, timeout=60):
        captured.update(system=system, fewshot=fewshot)
        return "ok"

    monkeypatch.setattr(TextProcessor, "_chat", fake_chat)
    TextProcessor(mode="smart", prompt_lang="en").process("um hello")
    assert "Keep the language of the input" in captured["system"]
    assert captured["fewshot"][0][1].startswith("I wanted")
    TextProcessor(mode="smart").process("aehm hallo")
    assert captured["system"].startswith("Du bist")


def test_clean_response_strips_english_preamble():
    assert tp._clean_response("Here is the cleaned text: Hello world.") == "Hello world."
    assert tp._clean_response("Sure, we meet at five.") == "Sure, we meet at five."
