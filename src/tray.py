"""VoZii System Tray — haZii Design."""

import pyperclip
import pystray
from PIL import Image, ImageDraw

from src.state import AppState
from src.theme import BRAND

STATE_COLORS = {
    AppState.IDLE: BRAND["cyan"],
    AppState.RECORDING: BRAND["red"],
    AppState.TRANSCRIBING: BRAND["amber"],
}


def _hex_to_rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _create_icon(color, size=64):
    """Sauberes VoZii Icon — V auf solidem Hintergrund, keine Transparenz-Artefakte."""
    bg = _hex_to_rgb(BRAND["bg"])
    fg = _hex_to_rgb(color)

    img = Image.new("RGB", (size, size), bg)
    draw = ImageDraw.Draw(img)

    # V zeichnen
    cx, cy = size // 2, size // 2
    lw = max(2, size // 10)
    ox = size * 35 // 100
    oy = size * 30 // 100

    draw.line([(cx - ox, cy - oy), (cx, cy + oy)], fill=fg, width=lw)
    draw.line([(cx + ox, cy - oy), (cx, cy + oy)], fill=fg, width=lw)

    return img


class TrayApp:
    def __init__(self, state_manager, on_quit, hotkey_str="", backend_name="",
                 mic_name="", on_open_settings=None, on_open_log=None, history=None):
        self.state_manager = state_manager
        self.on_quit = on_quit
        self.hotkey_str = hotkey_str
        self.backend_name = backend_name
        self.mic_name = mic_name
        self.on_open_settings = on_open_settings
        self.on_open_log = on_open_log
        self.history = history
        self._icons = {s: _create_icon(c) for s, c in STATE_COLORS.items()}
        self._icon = None

    def _menu_items(self):
        """Generator — pystray ruft ihn bei jedem Oeffnen neu auf, daher sind
        Status-Label und Historie immer aktuell (kein Cross-Thread-Neubau)."""
        labels = {AppState.IDLE: "Bereit", AppState.RECORDING: "Aufnahme...",
                  AppState.TRANSCRIBING: "Transkribiere..."}
        yield pystray.MenuItem(f"VoZii — {labels.get(self.state_manager.state, '?')}",
                               None, enabled=False)
        if self.hotkey_str:
            yield pystray.MenuItem(
                f"Hotkey: {self.hotkey_str.upper().replace('+', ' + ')}", None, enabled=False)
        if self.mic_name:
            mic = self.mic_name if len(self.mic_name) <= 35 else self.mic_name[:32] + "..."
            yield pystray.MenuItem(f"Mikrofon: {mic}", None, enabled=False)
        yield pystray.Menu.SEPARATOR
        if self.history is not None:
            yield pystray.MenuItem("Letzte Transkriptionen", pystray.Menu(self._history_items))
        if self.on_open_settings:
            yield pystray.MenuItem("Einstellungen", self._open_settings)
        if self.on_open_log:
            yield pystray.MenuItem("Log oeffnen", self._open_log)
        yield pystray.MenuItem("Beenden", self._quit)

    def _history_items(self):
        """Generator fuer das Historie-Submenu — Klick kopiert den Volltext."""
        entries = self.history.get_recent(5) if self.history else []
        if not entries:
            yield pystray.MenuItem("(leer)", None, enabled=False)
            return
        for entry in entries:
            label = " ".join(entry["text"].split())
            if len(label) > 40:
                label = label[:37] + "..."
            yield pystray.MenuItem(label, self._make_copy_action(entry["text"]))

    @staticmethod
    def _make_copy_action(text):
        """Action-Closure mit exakt (icon, item) — pystray validiert die
        Signatur ueber co_argcount und lehnt alles andere ab (auch Lambdas
        mit Default-Parametern!)."""
        def _copy(icon, item):
            pyperclip.copy(text)
        return _copy

    def _open_settings(self, icon, item):
        if self.on_open_settings:
            self.on_open_settings()
            icon.stop()

    def _open_log(self, icon, item):
        if self.on_open_log:
            try:
                self.on_open_log()
            except Exception:
                pass

    def _quit(self, icon, item):
        self.on_quit()
        icon.stop()

    def _on_state_change(self, new_state):
        if self._icon:
            self._icon.icon = self._icons.get(new_state, self._icons[AppState.IDLE])
            # Generator-Menu liest sich beim Oeffnen selbst neu — update_menu
            # synchronisiert nur die Plattformen, die nicht zur Anzeigezeit bauen
            self._icon.update_menu()

    def run(self):
        self.state_manager.on_change(self._on_state_change)
        self._icon = pystray.Icon("VoZii", self._icons[AppState.IDLE],
                                   "VoZii", pystray.Menu(self._menu_items))
        self._icon.run()
