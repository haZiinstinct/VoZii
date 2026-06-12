"""Tray-Menue: pystray validiert Action-Signaturen (co_argcount == 0/1/2).

Regressionstest fuer den v1.5.0-Crash: ein Lambda mit Default-Parameter
(3 Argumente) liess pystray._assert_action mit ValueError abbrechen —
die MenuItem-KONSTRUKTION reicht, um das zu fangen (kein Icon-Loop noetig).
"""

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


def _menu_items(menu):
    # pystray.Menu(*items) -> items via iteration (sichtbare Items)
    return list(menu)


def test_history_menu_builds_with_entries():
    """v1.5.0-Crash: MenuItem-Bau mit History-Eintraegen darf nicht raisen."""
    tray = _tray(FakeHistory(["erster Text", "zweiter Text", "dritter Text"]))
    menu = tray._build_history_menu()
    items = _menu_items(menu)
    assert len(items) == 3
    # neueste zuerst
    assert items[0].text == "erster Text"


def test_history_menu_action_copies_full_text(monkeypatch):
    copied = []
    import src.tray as tray_mod
    monkeypatch.setattr(tray_mod.pyperclip, "copy", copied.append)

    long_text = "Dies ist ein sehr langer Transkriptionstext, der gekuerzt angezeigt wird"
    tray = _tray(FakeHistory([long_text]))
    items = _menu_items(tray._build_history_menu())

    assert items[0].text == long_text[:37] + "..."
    items[0](None)  # MenuItem.__call__(icon) loest die Action aus
    assert copied == [long_text]  # Volltext, nicht das gekuerzte Label


def test_history_menu_empty_and_none():
    items = _menu_items(_tray(FakeHistory([]))._build_history_menu())
    assert len(items) == 1 and not items[0].enabled

    assert _tray(None)._build_history_menu() is None


def test_full_menu_builds_without_errors():
    """Faengt Signatur-Fehler ALLER Menue-Actions (Einstellungen, Log, Beenden...)."""
    for history in (None, FakeHistory([]), FakeHistory(["abc"])):
        tray = _tray(history)
        for state in (AppState.IDLE, AppState.RECORDING, AppState.TRANSCRIBING):
            tray.state_manager.set_state(state)
            menu = tray._build_menu()
            assert len(_menu_items(menu)) >= 4
