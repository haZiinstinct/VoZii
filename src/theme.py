"""VoZii — haZii Corporate Design Farbpalette und Fonts."""

from src.fonts import load_brand_fonts

# haZii Brand Colors (live abgeglichen mit hazii.org, 2026-06)
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
    "border": "#1e1e2a",        # entspricht ~ white/8% auf bg (Website: #ffffff14)
    "border_hover": "#0d4c5f",  # entspricht ~ cyan/30% auf card (Website: #00d4ff4d)
    "red": "#ef4444",
    "amber": "#f59e0b",
    "green": "#22c55e",
}

# Inter + JetBrains Mono (wie hazii.org), gebuendelt + privat geladen;
# Fallback auf Segoe UI/Consolas wenn das Laden fehlschlaegt
FONT_BODY, FONT_MONO = load_brand_fonts()

APP_NAME = "VoZii"
APP_SUBTITLE = "Voice-to-Text by haZii"
