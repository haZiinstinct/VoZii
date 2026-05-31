"""VoZii — haZii Corporate Design Farbpalette und Fonts."""

from src.platform_utils import IS_MAC

# haZii Brand Colors (extrahiert aus hazii.org)
BRAND = {
    "bg": "#0a0a0f",
    "bg_darker": "#06060a",
    "card": "#12121a",
    "card_hover": "#1a1a25",
    "cyan": "#00d4ff",
    "cyan_dim": "#00a8cc",
    "text": "#e2e8f0",
    "text_dim": "#94a3b8",
    "text_bright": "#f8fafc",
    "border": "#1e1e2a",
    "red": "#ef4444",
    "amber": "#f59e0b",
    "green": "#22c55e",
}

# Fonts — plattformabhaengig (Tk faellt bei fehlender Schrift still zurueck)
if IS_MAC:
    FONT_BODY = "SF Pro Text"    # macOS System-Font
    FONT_MONO = "Menlo"          # macOS Monospace
else:
    FONT_BODY = "Segoe UI"       # Windows (Inter nicht vorinstalliert)
    FONT_MONO = "Consolas"       # Windows (JetBrains Mono nicht vorinstalliert)

APP_NAME = "VoZii"
APP_SUBTITLE = "Voice-to-Text by haZii"
