"""Kontrast der Farbpaare, die im Audit 2026-11 unter WCAG AA lagen."""

import pytest

from src.theme import BRAND


def _lum(hex_color: str) -> float:
    def chan(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast(fg: str, bg: str) -> float:
    a, b = sorted((_lum(BRAND[fg]), _lum(BRAND[bg])), reverse=True)
    return (a + 0.05) / (b + 0.05)


@pytest.mark.parametrize("fg, bg", [
    ("text_bright", "cyan_deep"),    # aktives Segment
    ("text_bright", "cyan_deeper"),  # aktives Segment, Hover
    ("text_dim", "card_hover"),      # Ollama-Abbrechen, Hover
    ("bg", "red"),                   # Download-Abbrechen
    ("bg", "red_hover"),             # Download-Abbrechen, Hover
    ("bg", "cyan"), ("bg", "cyan_dim"),
    ("text", "bg"), ("text", "card"), ("text_dim", "bg"), ("text_dim", "card"),
    ("red", "bg"), ("red", "card"), ("amber", "card"), ("green", "card"),
])
def test_textkontrast_mindestens_aa(fg, bg):
    assert contrast(fg, bg) >= 4.5, f"{fg} auf {bg}: {contrast(fg, bg):.2f}"
