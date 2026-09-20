"""M5: Hotkey-Health, GPU-Cache, insert_text-Verhalten."""

import threading

from src import hardware, text_inserter
from src.hotkey import HotkeyManager


class _FakeListener:
    def __init__(self, alive=True):
        self._alive = alive

    def is_alive(self):
        return self._alive

    def stop(self):
        self._alive = False


def _manager(hotkey="ctrl+shift+space", on_activate=None, on_deactivate=None):
    m = HotkeyManager(hotkey,
                      on_activate=on_activate or (lambda: None),
                      on_deactivate=on_deactivate or (lambda: None))
    # Callbacks laufen ueber einen eigenen Thread; is_healthy() prueft ihn mit
    m._dispatcher = _FakeListener(alive=True)
    return m


def test_is_healthy_false_before_start():
    m = HotkeyManager("ctrl+shift+space", on_activate=lambda: None,
                      on_deactivate=lambda: None)
    assert not m.is_healthy()


def test_is_healthy_detects_dead_dispatcher():
    """Ohne laufenden Dispatcher-Thread kaeme kein Callback mehr an."""
    m = _manager()
    m._kb_listener = _FakeListener(alive=True)
    assert m.is_healthy()
    m._dispatcher = _FakeListener(alive=False)
    assert not m.is_healthy()


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


# --- Callback-Reihenfolge / verpasstes Release ---

def test_callbacks_run_in_order():
    """Frueher bekam jedes Event einen eigenen Thread — bei kurzem Druck konnte
    das Release-Callback vor dem Press-Callback laufen und die Aufnahme lief
    endlos weiter."""
    seen = []
    done = threading.Event()

    def activate():
        seen.append("on")

    def deactivate():
        seen.append("off")
        done.set()

    m = HotkeyManager("f9", on_activate=activate, on_deactivate=deactivate)
    m._ensure_dispatcher()
    try:
        m._handle_press("f9")
        m._handle_release("f9")
        assert done.wait(2), "Callbacks wurden nicht ausgefuehrt"
        assert seen == ["on", "off"]
    finally:
        m._dispatcher_stop.set()


def test_release_if_stuck_recovers_missed_release(monkeypatch):
    """Verschlucktes Release-Event: der Manager haelt sich fuer 'gedrueckt' und
    ignoriert jeden weiteren Druck — bis der Watchdog es nachholt."""
    fired = threading.Event()
    m = HotkeyManager("f9", on_activate=lambda: None,
                      on_deactivate=fired.set)
    m._ensure_dispatcher()
    try:
        monkeypatch.setattr(m, "_physically_held", lambda: True)
        m._handle_press("f9")
        assert m.release_if_stuck() is False  # noch gedrueckt -> nichts tun

        monkeypatch.setattr(m, "_physically_held", lambda: False)
        assert m.release_if_stuck() is True
        assert fired.wait(2)
        assert m._active is False
        assert m._pressed_parts == set()
        assert m.release_if_stuck() is False  # nur einmal
    finally:
        m._dispatcher_stop.set()


def test_release_if_stuck_ignores_toggle_mode():
    m = HotkeyManager("f9", on_activate=lambda: None, on_deactivate=lambda: None,
                      mode="toggle")
    m._active = True
    assert m.release_if_stuck() is False


# --- GPU-Cache ---

def test_gpu_cache_hit_skips_detection(monkeypatch):
    monkeypatch.setattr(hardware, "_refresh_gpu_cache", lambda *a: None)

    def boom():
        raise AssertionError("detect_gpu darf bei Cache-Hit nicht synchron laufen")
    monkeypatch.setattr(hardware, "detect_gpu", boom)

    config = {"gpu_cache_type": "nvidia", "gpu_cache_name": "RTX 4070",
              "gpu_cache_at": None}
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
    """Ersetzt src.winclip: merkt sich Inhalt + Schreibreihenfolge."""

    def __init__(self, initial="", writable=True):
        self.content = initial
        self.history = []
        self.writable = writable
        self.pastes = 0

    def set_text(self, text):
        if not self.writable:
            return False
        self.content = text
        self.history.append(text)
        return True

    def get_text(self):
        return self.content


def _patch_inserter(monkeypatch, clip, paste_ok=True, modifiers=False):
    monkeypatch.setattr(text_inserter.winclip, "set_text", clip.set_text)
    monkeypatch.setattr(text_inserter.winclip, "get_text", clip.get_text)
    monkeypatch.setattr(text_inserter.winclip, "modifiers_held", lambda: modifiers)
    # nicht echte Sekunden auf den Timeout warten
    monkeypatch.setattr(text_inserter, "_wait_for_modifier_release",
                        lambda *a: not modifiers)
    monkeypatch.setattr(text_inserter.time, "sleep", lambda *a: None)

    def fake_ctrl_v():
        clip.pastes += 1
        return paste_ok
    monkeypatch.setattr(text_inserter.winclip, "send_ctrl_v", fake_ctrl_v)
    # Restore laeuft im Hintergrund-Thread — hier direkt ausfuehren
    monkeypatch.setattr(text_inserter, "_restore_later",
                        lambda previous, ours, delay_s=0: clip.set_text(previous))


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
    _patch_inserter(monkeypatch, clip, paste_ok=False)
    assert text_inserter.insert_text("neuer text") is False
    # Kein Restore bei Fehlschlag — der Text ist der Fallback fuer den Nutzer
    assert clip.content == "neuer text"


def test_insert_text_empty_is_noop(monkeypatch):
    clip = _FakeClipboard(initial="vorher")
    _patch_inserter(monkeypatch, clip)
    assert text_inserter.insert_text("") is True
    assert clip.history == []


def test_insert_text_aborts_when_clipboard_unwritable(monkeypatch):
    """Ablage von einer anderen App belegt: lieber gar nicht einfuegen als den
    ALTEN Inhalt in das Zieldokument zu kippen."""
    clip = _FakeClipboard(initial="vorher", writable=False)
    _patch_inserter(monkeypatch, clip)
    assert text_inserter.insert_text("neuer text") is False
    assert clip.pastes == 0
    assert clip.content == "vorher"


def test_insert_text_aborts_while_modifiers_held(monkeypatch):
    """Ctrl/Shift noch gedrueckt: aus Ctrl+V wuerde Ctrl+Shift+V."""
    clip = _FakeClipboard(initial="vorher")
    _patch_inserter(monkeypatch, clip, modifiers=True)
    assert text_inserter.insert_text("neuer text") is False
    assert clip.pastes == 0
    assert clip.content == "neuer text"  # bleibt als Fallback in der Ablage


# --- winclip (Win32-Zwischenablage) ---

def test_winclip_roundtrip_preserves_unicode():
    """Umlaute/Emoji muessen die CF_UNICODETEXT-Runde ueberleben."""
    import sys

    import pytest

    from src import winclip
    if sys.platform != "win32":
        pytest.skip("Windows-only")

    previous = winclip.get_text()
    try:
        sample = "Grüße aus München — 100 % ✓"
        assert winclip.set_text(sample) is True
        assert winclip.get_text() == sample
    finally:
        if previous is not None:
            winclip.set_text(previous)


def test_winclip_sequence_number_advances_on_write():
    import sys

    import pytest

    from src import winclip
    if sys.platform != "win32":
        pytest.skip("Windows-only")

    previous = winclip.get_text()
    try:
        before = winclip.sequence_number()
        winclip.set_text("vozii-seq-test")
        assert winclip.sequence_number() != before
    finally:
        if previous is not None:
            winclip.set_text(previous)


def test_restart_keeps_dispatcher_alive(monkeypatch):
    """restart() setzt erst stop() — der Dispatcher darf danach nicht als
    'lebt noch' durchgehen und dann wegsterben."""
    fired = threading.Event()
    m = HotkeyManager("f9", on_activate=lambda: None, on_deactivate=lambda: None)
    monkeypatch.setattr(m, "_kb_listener", None)
    monkeypatch.setattr(HotkeyManager, "start",
                        lambda self: self._ensure_dispatcher())
    m.start()
    first = m._dispatcher
    m.restart()
    try:
        assert m._dispatcher_stop.is_set() is False
        assert m._dispatcher.is_alive()
        assert m._dispatcher is not first
        m._fire(fired.set)
        assert fired.wait(2), "Dispatcher verarbeitet nach restart() nichts mehr"
    finally:
        m._dispatcher_stop.set()
