"""VoZii Hotkey Manager — unterstuetzt Tastatur UND Maustasten (Mouse4, Mouse5 etc.)."""

import threading

from pynput import keyboard, mouse


# Map readable names to pynput Key objects
SPECIAL_KEYS = {
    "ctrl": {keyboard.Key.ctrl_l, keyboard.Key.ctrl_r, keyboard.Key.ctrl},
    "shift": {keyboard.Key.shift_l, keyboard.Key.shift_r, keyboard.Key.shift},
    "alt": {keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt},
    "space": {keyboard.Key.space},
    "tab": {keyboard.Key.tab},
    "enter": {keyboard.Key.enter},
    "f1": {keyboard.Key.f1}, "f2": {keyboard.Key.f2}, "f3": {keyboard.Key.f3},
    "f4": {keyboard.Key.f4}, "f5": {keyboard.Key.f5}, "f6": {keyboard.Key.f6},
    "f7": {keyboard.Key.f7}, "f8": {keyboard.Key.f8}, "f9": {keyboard.Key.f9},
    "f10": {keyboard.Key.f10}, "f11": {keyboard.Key.f11}, "f12": {keyboard.Key.f12},
    "caps_lock": {keyboard.Key.caps_lock},
    "scroll_lock": {keyboard.Key.scroll_lock},
    "pause": {keyboard.Key.pause},
    "insert": {keyboard.Key.insert},
    "delete": {keyboard.Key.delete},
    "home": {keyboard.Key.home},
    "end": {keyboard.Key.end},
    "page_up": {keyboard.Key.page_up},
    "page_down": {keyboard.Key.page_down},
}

# Mouse button names
MOUSE_BUTTONS = {
    "mouse1": mouse.Button.left,
    "mouse2": mouse.Button.right,
    "mouse3": mouse.Button.middle,
}

# Mouse4/Mouse5 (x1/x2) — pynput uses Button.x1, Button.x2 on Windows
try:
    MOUSE_BUTTONS["mouse4"] = mouse.Button.x1
    MOUSE_BUTTONS["mouse5"] = mouse.Button.x2
except AttributeError:
    pass  # Not available on all platforms


def _parse_hotkey(hotkey_str: str) -> list[str]:
    """Parse 'ctrl+shift+space' or 'mouse4' into parts."""
    return [part.strip().lower() for part in hotkey_str.split("+")]


def _key_matches_part(key, part: str) -> bool:
    """Check if a keyboard key matches a hotkey part name."""
    if part in SPECIAL_KEYS:
        return key in SPECIAL_KEYS[part]
    if len(part) == 1:
        if hasattr(key, "char") and key.char is not None:
            return key.char.lower() == part.lower()
        if hasattr(key, "vk") and key.vk is not None:
            return key.vk == ord(part.upper())
    return False


def _mouse_matches_part(button, part: str) -> bool:
    """Check if a mouse button matches a hotkey part name."""
    if part in MOUSE_BUTTONS:
        return button == MOUSE_BUTTONS[part]
    return False


def key_to_name(key) -> str:
    """Convert a pynput keyboard key to a readable name."""
    for name, key_set in SPECIAL_KEYS.items():
        if key in key_set:
            return name
    if hasattr(key, "char") and key.char is not None:
        return key.char.lower()
    if hasattr(key, "vk") and key.vk is not None:
        if 65 <= key.vk <= 90:
            return chr(key.vk).lower()
        if 48 <= key.vk <= 57:
            return chr(key.vk)
    return str(key)


def mouse_button_to_name(button) -> str:
    """Convert a pynput mouse button to a readable name."""
    for name, btn in MOUSE_BUTTONS.items():
        if button == btn:
            return name
    return str(button)


class HotkeyManager:
    """Global hotkey manager — Tastatur + Maustasten, Push-to-Talk + Toggle."""

    def __init__(self, hotkey_str: str, on_activate, on_deactivate, mode: str = "push_to_talk"):
        self.hotkey_str = hotkey_str
        self.on_activate = on_activate
        self.on_deactivate = on_deactivate
        self.mode = mode
        self._active = False
        self._kb_listener = None
        self._mouse_listener = None
        self._parts = _parse_hotkey(hotkey_str)
        self._pressed_parts = set()
        self._has_mouse_parts = any(p.startswith("mouse") for p in self._parts)
        self._has_kb_parts = any(not p.startswith("mouse") for p in self._parts)

    def _match_key(self, key) -> str | None:
        for part in self._parts:
            if not part.startswith("mouse") and _key_matches_part(key, part):
                return part
        return None

    def _match_mouse(self, button) -> str | None:
        for part in self._parts:
            if part.startswith("mouse") and _mouse_matches_part(button, part):
                return part
        return None

    def _all_pressed(self) -> bool:
        return self._pressed_parts == set(self._parts)

    def _handle_press(self, part: str):
        self._pressed_parts.add(part)
        if self._all_pressed():
            if self.mode == "push_to_talk":
                if not self._active:
                    self._active = True
                    self._fire(self.on_activate)
            elif self.mode == "toggle":
                if not self._active:
                    self._active = True
                    self._fire(self.on_activate)
                else:
                    self._active = False
                    self._fire(self.on_deactivate)

    def _handle_release(self, part: str):
        self._pressed_parts.discard(part)
        if self.mode == "push_to_talk" and self._active:
            self._active = False
            self._fire(self.on_deactivate)

    # Keyboard callbacks
    def _on_kb_press(self, key):
        part = self._match_key(key)
        if part:
            self._handle_press(part)

    def _on_kb_release(self, key):
        part = self._match_key(key)
        if part:
            self._handle_release(part)

    # Mouse callbacks
    def _on_mouse_click(self, x, y, button, pressed):
        part = self._match_mouse(button)
        if part:
            if pressed:
                self._handle_press(part)
            else:
                self._handle_release(part)

    def _fire(self, callback):
        threading.Thread(target=callback, daemon=True).start()

    def start(self):
        if self._has_kb_parts:
            self._kb_listener = keyboard.Listener(
                on_press=self._on_kb_press,
                on_release=self._on_kb_release,
            )
            self._kb_listener.daemon = True
            self._kb_listener.start()

        if self._has_mouse_parts:
            self._mouse_listener = mouse.Listener(
                on_click=self._on_mouse_click,
            )
            self._mouse_listener.daemon = True
            self._mouse_listener.start()

        # If hotkey is ONLY mouse buttons, still need kb listener for combos like ctrl+mouse4
        if not self._has_kb_parts and self._has_mouse_parts:
            pass  # only mouse listener needed
        elif self._has_kb_parts and self._has_mouse_parts:
            pass  # both already started

    def stop(self):
        if self._kb_listener:
            self._kb_listener.stop()
            self._kb_listener = None
        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener = None
