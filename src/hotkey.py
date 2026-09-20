"""VoZii Hotkey Manager — unterstuetzt Tastatur UND Maustasten (Mouse4, Mouse5 etc.)."""

import ctypes
import logging
import queue
import sys
import threading

from pynput import keyboard, mouse

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"


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

# Windows-VK-Codes je Hotkey-Teil — nur fuer die Stuck-Erkennung: geht ein
# Release-Event verloren (Hook kurz weg, Fokuswechsel, Remote-Session), haelt
# der Manager sich fuer "noch gedrueckt" und ignoriert jeden weiteren Druck.
# GetAsyncKeyState sagt, was der Nutzer *wirklich* haelt.
_PART_VKS = {
    "ctrl": (0x11,), "shift": (0x10,), "alt": (0x12,),
    "space": (0x20,), "tab": (0x09,), "enter": (0x0D,),
    "caps_lock": (0x14,), "scroll_lock": (0x91,), "pause": (0x13,),
    "insert": (0x2D,), "delete": (0x2E,), "home": (0x24,), "end": (0x23,),
    "page_up": (0x21,), "page_down": (0x22,),
    "mouse1": (0x01,), "mouse2": (0x02,), "mouse3": (0x04,),
    "mouse4": (0x05,), "mouse5": (0x06,),
}
_PART_VKS.update({f"f{n}": (0x6F + n,) for n in range(1, 13)})


def _part_vks(part: str) -> tuple[int, ...]:
    if part in _PART_VKS:
        return _PART_VKS[part]
    if len(part) == 1:
        return (ord(part.upper()),)
    return ()


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
        # Callbacks laufen serialisiert ueber genau einen Thread. Frueher bekam
        # jedes Event einen eigenen Thread — bei kurzem Druck konnte das
        # Release-Callback vor dem Press-Callback ankommen und die Aufnahme
        # lief endlos weiter.
        self._events = queue.Queue()
        self._dispatcher = None
        self._dispatcher_stop = threading.Event()

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
        self._events.put(callback)

    def _ensure_dispatcher(self):
        # Auch das Stop-Flag pruefen: nach stop() lebt der Thread noch bis zu
        # einem Queue-Timeout weiter — ohne diese Bedingung wuerde restart()
        # ihn fuer gesund halten und danach staende gar kein Dispatcher mehr
        if (self._dispatcher is not None and self._dispatcher.is_alive()
                and not self._dispatcher_stop.is_set()):
            return
        if self._dispatcher is not None:
            self._dispatcher_stop.set()
            self._dispatcher.join(timeout=1)
        self._dispatcher_stop.clear()
        self._dispatcher = threading.Thread(target=self._dispatch_loop, daemon=True,
                                            name="hotkey-dispatch")
        self._dispatcher.start()

    def _dispatch_loop(self):
        while not self._dispatcher_stop.is_set():
            try:
                callback = self._events.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                callback()
            except Exception:
                log.exception("Hotkey-Callback fehlgeschlagen")

    def start(self):
        self._ensure_dispatcher()
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

    def stop(self):
        self._dispatcher_stop.set()
        if self._kb_listener:
            self._kb_listener.stop()
            self._kb_listener = None
        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener = None

    def _physically_held(self) -> bool:
        """Haelt der Nutzer den Hotkey laut Windows gerade wirklich?"""
        if not IS_WINDOWS:
            return True  # ohne Gegenprobe lieber nichts erzwingen
        try:
            get_state = ctypes.windll.user32.GetAsyncKeyState
        except Exception:
            return True
        for part in self._parts:
            vks = _part_vks(part)
            if not vks:
                return True  # unbekannter Teil -> nicht raten
            if not any(get_state(vk) & 0x8000 for vk in vks):
                return False
        return True

    def release_if_stuck(self) -> bool:
        """Loest ein verlorengegangenes Release nach. Returns True, wenn
        nachgeholt wurde.

        Ohne das bliebe der Manager nach einem verschluckten Release-Event
        dauerhaft im Zustand "gedrueckt" — der Hotkey waere bis zum
        App-Neustart tot und die Aufnahme liefe weiter.
        """
        if not self._active or self.mode != "push_to_talk":
            return False
        if self._physically_held():
            return False
        log.warning("Hotkey-Release verpasst — hole Aufnahme-Stopp nach")
        self._pressed_parts.clear()
        self._active = False
        self._fire(self.on_deactivate)
        return True

    def is_healthy(self) -> bool:
        """Leben alle benoetigten Listener noch? Windows entfernt Low-Level-
        Hooks gelegentlich (Hook-Timeout) — dann ist der Hotkey still tot."""
        if self._has_kb_parts:
            if self._kb_listener is None or not self._kb_listener.is_alive():
                return False
        if self._has_mouse_parts:
            if self._mouse_listener is None or not self._mouse_listener.is_alive():
                return False
        if self._dispatcher is None or not self._dispatcher.is_alive():
            return False
        return True

    def restart(self):
        """Listener neu aufbauen (vom Watchdog gerufen)."""
        log.warning("Hotkey-Listener werden neu gestartet")
        was_active = self._active
        self.stop()
        self._pressed_parts = set()
        self._active = False
        self.start()
        if was_active:
            # Waehrend einer laufenden Aufnahme neu gestartet: das Release
            # kommt nie mehr an, also selbst stoppen (sonst laeuft sie ewig)
            self._fire(self.on_deactivate)
