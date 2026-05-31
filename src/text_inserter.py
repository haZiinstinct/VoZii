import time

import pyautogui
import pyperclip

from src.platform_utils import paste_hotkey


def insert_text(text: str):
    """Text an Cursorposition einfuegen. Text bleibt IMMER in Zwischenablage als Fallback."""
    if not text:
        return

    pyperclip.copy(text)
    time.sleep(0.05)

    try:
        pyautogui.hotkey(*paste_hotkey())
    except Exception:
        pass  # Kein fokussiertes Textfeld — Text ist trotzdem in Zwischenablage
