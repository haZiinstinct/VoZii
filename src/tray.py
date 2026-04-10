import threading

from PIL import Image, ImageDraw
import pystray

from src.state import AppState
from src.theme import BRAND

# Icon colors per state
STATE_COLORS = {
    AppState.IDLE: BRAND["cyan"],
    AppState.RECORDING: BRAND["red"],
    AppState.TRANSCRIBING: BRAND["amber"],
    AppState.ERROR: BRAND["text_dim"],
}


def _create_icon(color: str, size: int = 64) -> Image.Image:
    """Generate a VoZii icon — colored circle with mic shape."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 4
    draw.ellipse([margin, margin, size - margin, size - margin], fill=color)
    cx, cy = size // 2, size // 2
    # Mic body
    draw.rounded_rectangle(
        [cx - 8, cy - 16, cx + 8, cy + 4],
        radius=8, fill="white",
    )
    # Mic stand
    draw.arc([cx - 14, cy - 8, cx + 14, cy + 14], start=0, end=180, fill="white", width=2)
    draw.line([cx, cy + 14, cx, cy + 20], fill="white", width=2)
    draw.line([cx - 8, cy + 20, cx + 8, cy + 20], fill="white", width=2)
    return img


class TrayApp:
    def __init__(self, state_manager, on_quit,
                 hotkey_str="", backend_name="",
                 on_open_settings=None):
        self.state_manager = state_manager
        self.on_quit = on_quit
        self.hotkey_str = hotkey_str
        self.backend_name = backend_name
        self.on_open_settings = on_open_settings
        self._icons = {state: _create_icon(color) for state, color in STATE_COLORS.items()}
        self._icon = None

    def _build_menu(self):
        state = self.state_manager.state
        status_text = {
            AppState.IDLE: "Bereit",
            AppState.RECORDING: "Aufnahme...",
            AppState.TRANSCRIBING: "Transkribiere...",
            AppState.ERROR: "Fehler",
        }

        items = [
            pystray.MenuItem(f"VoZii — {status_text.get(state, '?')}", None, enabled=False),
        ]

        if self.hotkey_str:
            items.append(pystray.MenuItem(
                f"Hotkey: {self.hotkey_str.upper().replace('+', ' + ')}",
                None, enabled=False,
            ))

        if self.backend_name:
            items.append(pystray.MenuItem(
                f"Backend: {self.backend_name}",
                None, enabled=False,
            ))

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

    def _on_state_change(self, new_state: AppState):
        if self._icon:
            self._icon.icon = self._icons.get(new_state, self._icons[AppState.IDLE])
            self._icon.update_menu()

    def run(self):
        self.state_manager.on_change(self._on_state_change)
        self._icon = pystray.Icon(
            name="VoZii",
            icon=self._icons[AppState.IDLE],
            title="VoZii",
            menu=self._build_menu(),
        )
        self._icon.run()
