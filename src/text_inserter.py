import time

import pyautogui
import pyperclip


def insert_text(text: str, restore_clipboard: bool = False):
    """Text an Cursorposition einfuegen. Text bleibt IMMER in Zwischenablage als Fallback."""
    if not text:
        return

    # Text in Zwischenablage kopieren (bleibt dort als Fallback)
    pyperclip.copy(text)
    time.sleep(0.05)

    # Versuche Ctrl+V an aktuellem Cursor
    try:
        pyautogui.hotkey("ctrl", "v")
    except Exception:
        pass  # Kein fokussiertes Textfeld — Text ist trotzdem in Zwischenablage
