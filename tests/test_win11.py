"""M5: Hotkey-Health, GPU-Cache, insert_text-Verhalten."""

from src import hardware, text_inserter
from src.hotkey import HotkeyManager


class _FakeListener:
    def __init__(self, alive=True):
        self._alive = alive

    def is_alive(self):
        return self._alive

    def stop(self):
        self._alive = False


def _manager(hotkey="ctrl+shift+space"):
    return HotkeyManager(hotkey, on_activate=lambda: None, on_deactivate=lambda: None)


def test_is_healthy_false_before_start():
    assert not _manager().is_healthy()


def test_is_healthy_with_live_listener():
    m = _manager()
    m._kb_listener = _FakeListener(alive=True)
    assert m.is_healthy()


def test_is_healthy_detects_dead_listener():
    m = _manager()
    m._kb_listener = _FakeListener(alive=False)
    assert not m.is_healthy()


def test_is_healthy_checks_mouse_listener_for_mouse_hotkey():
    m = _manager("ctrl+mouse4")
    m._kb_listener = _FakeListener(alive=True)
    m._mouse_listener = _FakeListener(alive=False)
    assert not m.is_healthy()
    m._mouse_listener = _FakeListener(alive=True)
    assert m.is_healthy()


# --- GPU-Cache ---

def test_gpu_cache_hit_skips_detection(monkeypatch):
    monkeypatch.setattr(hardware, "_refresh_gpu_cache", lambda *a: None)

    def boom():
        raise AssertionError("detect_gpu darf bei Cache-Hit nicht synchron laufen")
    monkeypatch.setattr(hardware, "detect_gpu", boom)

    config = {"gpu_cache_type": "nvidia", "gpu_cache_name": "RTX 4070"}
    gpu_type, gpu_name, from_cache = hardware.detect_gpu_cached(config)
    assert (gpu_type, gpu_name, from_cache) == ("nvidia", "RTX 4070", True)


def test_gpu_cache_miss_detects_and_stores(monkeypatch):
    stored = {}
    monkeypatch.setattr(hardware, "detect_gpu", lambda: ("amd", "RX 6750 XT"))
    monkeypatch.setattr(hardware, "_store_gpu_cache",
                        lambda t, n: stored.update(t=t, n=n))

    gpu_type, gpu_name, from_cache = hardware.detect_gpu_cached({"gpu_cache_type": None})
    assert (gpu_type, gpu_name, from_cache) == ("amd", "RX 6750 XT", False)
    assert stored == {"t": "amd", "n": "RX 6750 XT"}


def test_gpu_cache_invalid_value_triggers_detection(monkeypatch):
    monkeypatch.setattr(hardware, "detect_gpu", lambda: ("cpu", ""))
    monkeypatch.setattr(hardware, "_store_gpu_cache", lambda t, n: None)
    _, _, from_cache = hardware.detect_gpu_cached({"gpu_cache_type": "quantum"})
    assert from_cache is False


# --- insert_text ---

class _FakeClipboard:
    def __init__(self, initial=""):
        self.content = initial
        self.history = []

    def copy(self, text):
        self.content = text
        self.history.append(text)

    def paste(self):
        return self.content


def _patch_inserter(monkeypatch, clip, paste_raises=False):
    monkeypatch.setattr(text_inserter.pyperclip, "copy", clip.copy)
    monkeypatch.setattr(text_inserter.pyperclip, "paste", clip.paste)
    monkeypatch.setattr(text_inserter, "_wait_for_modifier_release", lambda *a: None)
    monkeypatch.setattr(text_inserter.time, "sleep", lambda *a: None)

    def fake_hotkey(*keys):
        if paste_raises:
            raise RuntimeError("kein Fokus")
    monkeypatch.setattr(text_inserter.pyautogui, "hotkey", fake_hotkey)


def test_insert_text_restores_previous_clipboard(monkeypatch):
    clip = _FakeClipboard(initial="vorher")
    _patch_inserter(monkeypatch, clip)
    assert text_inserter.insert_text("neuer text", restore_clipboard=True) is True
    assert clip.history == ["neuer text", "vorher"]
    assert clip.content == "vorher"


def test_insert_text_keeps_clipboard_when_disabled(monkeypatch):
    clip = _FakeClipboard(initial="vorher")
    _patch_inserter(monkeypatch, clip)
    assert text_inserter.insert_text("neuer text", restore_clipboard=False) is True
    assert clip.content == "neuer text"


def test_insert_text_failure_keeps_text_in_clipboard(monkeypatch):
    clip = _FakeClipboard(initial="vorher")
    _patch_inserter(monkeypatch, clip, paste_raises=True)
    assert text_inserter.insert_text("neuer text") is False
    # Kein Restore bei Fehlschlag — der Text ist der Fallback fuer den Nutzer
    assert clip.content == "neuer text"


def test_insert_text_empty_is_noop(monkeypatch):
    clip = _FakeClipboard(initial="vorher")
    _patch_inserter(monkeypatch, clip)
    assert text_inserter.insert_text("") is True
    assert clip.history == []
