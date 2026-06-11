"""Brand-Fonts (Inter, JetBrains Mono) zur Laufzeit privat laden.

Die TTFs (OFL-Lizenz, gebuendelt unter assets/fonts) werden per
AddFontResourceExW mit FR_PRIVATE nur fuer diesen Prozess registriert —
keine Installation, keine Adminrechte. hazii.org nutzt exakt diese Fonts.
"""

import ctypes
import logging
import os
import sys

log = logging.getLogger(__name__)

_FR_PRIVATE = 0x10

_FONT_FILES = (
    "Inter-Regular.ttf",
    "Inter-Bold.ttf",
    "JetBrainsMono-Regular.ttf",
    "JetBrainsMono-Bold.ttf",
)

_FALLBACK = ("Segoe UI", "Consolas")


def _fonts_dir() -> str:
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", "fonts")


def load_brand_fonts() -> tuple[str, str]:
    """Returns (FONT_BODY, FONT_MONO): Brand-Fonts wenn ladbar, sonst System-Fallback."""
    try:
        add_font = ctypes.windll.gdi32.AddFontResourceExW
    except Exception:
        return _FALLBACK

    fonts_dir = _fonts_dir()
    loaded = 0
    for name in _FONT_FILES:
        path = os.path.join(fonts_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            if add_font(path, _FR_PRIVATE, 0) > 0:
                loaded += 1
        except Exception:
            log.debug("Font nicht ladbar: %s", path, exc_info=True)

    if loaded == len(_FONT_FILES):
        return "Inter", "JetBrains Mono"
    log.info("Brand-Fonts unvollstaendig (%d/%d) — nutze System-Fonts",
             loaded, len(_FONT_FILES))
    return _FALLBACK
