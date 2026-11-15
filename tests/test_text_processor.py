"""Korrektur via Ollama: Output-Cleaning, Chat-Request-Aufbau, Prompt-Sprache."""

import json

from src import text_processor as tp
from src.text_processor import TextProcessor, _clean_response


def test_nur_ein_modell_und_ein_modus():
    assert tp.MODEL == "llama3.2:1b"
    assert tp.MODES == ("off", "correct")
    # Unbekannte/alte Modi schalten ab statt zu raten
    assert TextProcessor(mode="smart").mode == "off"
    assert TextProcessor(mode="prompt").mode == "off"


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
    """process() im Korrektur-Modus baut den Chat-Request korrekt (System + Few-Shot + User)."""
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

    out = TextProcessor(mode="correct").process("aehm hallo")
    assert out == "bereinigt"  # getrimmt
    assert captured["url"].endswith("/api/chat")
    body = captured["body"]
    assert body["model"] == "llama3.2:1b"
    assert body["think"] is False
    assert body["stream"] is False
    roles = [m["role"] for m in body["messages"]]
    assert roles[0] == "system"
    assert roles[-1] == "user"
    assert body["messages"][-1]["content"] == "aehm hallo"
    assert "assistant" in roles  # Few-Shot vorhanden


def test_process_off_and_empty():
    assert TextProcessor(mode="off").process("x") == "x"
    assert TextProcessor(mode="correct").process("") == ""


def test_process_fallback_on_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("Ollama weg")
    monkeypatch.setattr(tp.urllib.request, "urlopen", boom)
    assert TextProcessor(mode="correct").process("mein text") == "mein text"


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


def test_prompt_sprache_nach_diktat_und_ui_sprache():
    assert tp.prompt_language("de", "en") == "de"
    assert tp.prompt_language("fr", "de") == "en"
    assert tp.prompt_language("auto", "de") == "de"
    assert tp.prompt_language("auto", "ja") == "en"


def test_englische_prompts_fuer_andere_sprachen(monkeypatch):
    captured = {}

    def fake_chat(self, system, fewshot, text, timeout=60):
        captured.update(system=system, fewshot=fewshot)
        return "ok"

    monkeypatch.setattr(TextProcessor, "_chat", fake_chat)
    TextProcessor(mode="correct", prompt_lang="en").process("um hello")
    assert "never translate" in captured["system"]
    assert captured["fewshot"][0][1].startswith("I wanted")
    TextProcessor(mode="correct").process("aehm hallo")
    assert captured["system"].startswith("Du korrigierst")


def test_clean_response_strips_english_preamble():
    assert tp._clean_response("Here is the cleaned text: Hello world.") == "Hello world."
    assert tp._clean_response("Sure, we meet at five.") == "Sure, we meet at five."


# --- Automatische Einrichtung ---

def _fake_setup(monkeypatch, states, installed=r"C:\x\ollama.exe", start_ok=True):
    """states: Abfolge der get_ollama_state()-Ergebnisse."""
    calls = []
    seq = list(states)
    monkeypatch.setattr(tp, "get_ollama_state", lambda model=tp.MODEL: seq.pop(0))
    monkeypatch.setattr(tp, "install_ollama", lambda *a: calls.append("install"))
    monkeypatch.setattr(tp, "is_ollama_installed", lambda: installed)
    monkeypatch.setattr(tp, "start_ollama", lambda path: calls.append("start") or start_ok)
    monkeypatch.setattr(tp, "pull_model", lambda m, *a: calls.append(("pull", m)))
    return calls


def test_ensure_ready_installiert_und_laedt_modell(monkeypatch):
    calls = _fake_setup(monkeypatch, ["not_installed", "no_model"])
    assert tp.ensure_ready() is True
    assert calls == ["install", ("pull", "llama3.2:1b")]


def test_ensure_ready_startet_ollama(monkeypatch):
    calls = _fake_setup(monkeypatch, ["installed_not_running", "ready"])
    tp.ensure_ready()
    assert calls == ["start"]


def test_ensure_ready_tut_nichts_wenn_bereit(monkeypatch):
    calls = _fake_setup(monkeypatch, ["ready"])
    tp.ensure_ready()
    assert calls == []


def test_ensure_ready_start_fehlgeschlagen(monkeypatch):
    _fake_setup(monkeypatch, ["installed_not_running"], start_ok=False)
    import pytest
    with pytest.raises(RuntimeError):
        tp.ensure_ready()


def test_laufzeit_start_installiert_nie(monkeypatch):
    calls = []
    monkeypatch.setattr(tp, "check_ollama", lambda: (False, []))
    monkeypatch.setattr(tp, "is_ollama_installed", lambda: None)
    monkeypatch.setattr(tp, "install_ollama", lambda *a: calls.append("install"))
    assert tp.start_ollama_if_needed() is False
    assert calls == []
