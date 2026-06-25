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
