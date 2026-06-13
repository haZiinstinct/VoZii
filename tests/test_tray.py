"""Tray-Menue: dynamisches Generator-Menue, Action-Signaturen.

pystray validiert Action-Signaturen (co_argcount == 0/1/2). Der v1.5.0-Crash
kam von einem Lambda mit Default-Parameter (3 Argumente). Hier wird das ganze
Menue (inkl. Historie-Submenu) mit echtem pystray gebaut, was die Validierung
ausloest.
"""

import pystray

from src.state import AppState, StateManager
from src.tray import TrayApp


class FakeHistory:
    def __init__(self, texts):
        self._texts = texts

    def get_recent(self, n=5):
        return [{"ts": "2026-06-12T10:00:00", "text": t} for t in self._texts[:n]]

    def count(self):
        return len(self._texts)


def _tray(history):
    return TrayApp(
        StateManager(), on_quit=lambda: None,
        hotkey_str="ctrl+shift+space", backend_name="CPU",
        mic_name="Testmikrofon", on_open_settings=lambda: None,
        on_open_log=lambda: None, history=history,
    )


def _items(generator_method):
    """pystray.Menu(generator) ruft das Callable auf — gibt die sichtbaren Items."""
    return list(pystray.Menu(generator_method))


def test_history_submenu_builds_with_entries():
    """v1.5.0-Crash: Historie-Items duerfen pystray nicht mit ValueError abbrechen."""
    tray = _tray(FakeHistory(["erster Text", "zweiter Text", "dritter Text"]))
    items = _items(tray._history_items)
    assert len(items) == 3
    assert items[0].text == "erster Text"  # neueste zuerst (FakeHistory-Reihenfolge)


def test_history_action_copies_full_text(monkeypatch):
    copied = []
    import src.tray as tray_mod
    monkeypatch.setattr(tray_mod.pyperclip, "copy", copied.append)

    long_text = "Dies ist ein sehr langer Transkriptionstext, der gekuerzt angezeigt wird"
    tray = _tray(FakeHistory([long_text]))
    items = _items(tray._history_items)

    assert items[0].text == long_text[:37] + "..."
    items[0](None)  # MenuItem.__call__(icon) loest die Action aus
    assert copied == [long_text]  # Volltext, nicht das gekuerzte Label


def test_history_empty_and_none():
    assert _items(_tray(FakeHistory([]))._history_items)[0].text == "(leer)"
    # history=None -> Submenu erscheint gar nicht im Hauptmenue
    tray = _tray(None)
    texts = [i.text for i in _items(tray._menu_items)]
    assert not any("Transkriptionen" in t for t in texts)


def test_full_menu_builds_for_all_states():
    """Faengt Signatur-Fehler ALLER Menue-Actions (Einstellungen, Log, Beenden...)."""
    for history in (None, FakeHistory([]), FakeHistory(["abc"])):
        tray = _tray(history)
        for state in (AppState.IDLE, AppState.RECORDING, AppState.TRANSCRIBING):
            tray.state_manager.set_state(state)
            items = _items(tray._menu_items)
            assert any("VoZii" in (i.text or "") for i in items)
            assert any(i.text == "Beenden" for i in items)


def test_menu_reflects_history_changes_live():
    """Generator wird bei jedem Bauen neu ausgewertet -> kein Stale-Cache."""
    hist = FakeHistory(["alt"])
    tray = _tray(hist)
    assert [i.text for i in _items(tray._history_items)] == ["alt"]
    hist._texts.insert(0, "neu")
    assert [i.text for i in _items(tray._history_items)] == ["neu", "alt"]
