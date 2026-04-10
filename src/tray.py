"""VoZii System Tray — haZii Design."""

from PIL import Image, ImageDraw, ImageFont
import pystray
from src.state import AppState
from src.theme import BRAND

STATE_COLORS = {
    AppState.IDLE: BRAND["cyan"],
    AppState.RECORDING: BRAND["red"],
    AppState.TRANSCRIBING: BRAND["amber"],
    AppState.ERROR: BRAND["text_dim"],
}


def _create_icon(color, size=64):
    """Modernes VoZii Icon — abgerundetes Quadrat mit V."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Abgerundetes Quadrat als Background
    m = 2
    draw.rounded_rectangle([m, m, size - m, size - m], radius=14,
                           fill="#0a0a0f", outline=color, width=3)

    # "V" in der Mitte
    cx, cy = size // 2, size // 2
    draw.line([(cx - 14, cy - 12), (cx, cy + 14)], fill=color, width=4)
    draw.line([(cx + 14, cy - 12), (cx, cy + 14)], fill=color, width=4)

    return img


class TrayApp:
    def __init__(self, state_manager, on_quit, hotkey_str="", backend_name="",
                 on_open_settings=None):
        self.state_manager = state_manager
        self.on_quit = on_quit
        self.hotkey_str = hotkey_str
        self.backend_name = backend_name
        self.on_open_settings = on_open_settings
        self._icons = {s: _create_icon(c) for s, c in STATE_COLORS.items()}
        self._icon = None

    def _build_menu(self):
        st = self.state_manager.state
        labels = {AppState.IDLE: "Bereit", AppState.RECORDING: "Aufnahme...",
                  AppState.TRANSCRIBING: "Transkribiere...", AppState.ERROR: "Fehler"}
        items = [pystray.MenuItem(f"VoZii — {labels.get(st, '?')}", None, enabled=False)]
        if self.hotkey_str:
            items.append(pystray.MenuItem(f"Hotkey: {self.hotkey_str.upper().replace('+', ' + ')}",
                                          None, enabled=False))
        items.append(pystray.Menu.SEPARATOR)
        if self.on_open_settings:
            items.append(pystray.MenuItem("Einstellungen", self._open_settings))
        items.append(pystray.MenuItem("Beenden", self._quit))
        return pystray.Menu(*items)

    def _open_settings(self, icon, item):
        if self.on_open_settings:
            self.on_open_settings()
            icon.stop()

    def _quit(self, icon, item):
        self.on_quit()
        icon.stop()

    def _on_state_change(self, new_state):
        if self._icon:
            self._icon.icon = self._icons.get(new_state, self._icons[AppState.IDLE])
            self._icon.update_menu()

    def run(self):
        self.state_manager.on_change(self._on_state_change)
        self._icon = pystray.Icon("VoZii", self._icons[AppState.IDLE],
                                   "VoZii", self._build_menu())
        self._icon.run()
