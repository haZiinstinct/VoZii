"""Filter gegen Whisper-Halluzinationen bei Stille.

Whisper erfindet bei (fast) stillen Aufnahmen gerne Phantom-Saetze aus den
Trainingsdaten — klassisch "Untertitelung des ZDF" oder "Thanks for watching".
Bewusst konservativ: verworfen wird nur, wenn die Aufnahme leise ODER sehr
kurz war UND der Text auf der Phantom-Liste steht. Normale leise Sprecher
werden nicht abgewuergt.
"""

import logging
import re

log = logging.getLogger(__name__)

# Empirisch: normales Sprechen liegt deutlich ueber 0.01 RMS (float32, -1..1);
# Raumstille mit offenem Mikro typischerweise unter 0.005.
RMS_SILENCE_THRESHOLD = 0.008

# Maximaldauer in Sekunden, unter der eine Aufnahme als "sehr kurz" gilt
SHORT_DURATION_S = 1.0

# Exakte Treffer (normalisiert: lowercase, ohne Satzzeichen)
PHANTOM_EXACT = {
    "vielen dank",
    "danke",
    "dankeschoen",
    "dankeschön",
    "tschuess",
    "tschüss",
    "bis zum naechsten mal",
    "bis zum nächsten mal",
    "you",
    "thank you",
    "thanks",
    "bye",
    "the end",
    "ende",
}

# Substring-Treffer — nur lange, eindeutige Phantom-Phrasen
PHANTOM_SUBSTRINGS = (
    "untertitelung des zdf",
    "untertitel im auftrag des zdf",
    "untertitel von stephanie geiges",
    "untertitelung aerzte ohne grenzen",
    "amara",  # "Untertitel der Amara.org-Community"
    "copyright wdr",
    "swr 2021",
    "thanks for watching",
    "thank you for watching",
    "please subscribe",
    "subtitles by",
)


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)
    return " ".join(text.split())


def is_hallucination(text: str, duration_s: float, rms: float) -> bool:
    """True wenn der Text mit hoher Sicherheit eine Stille-Halluzination ist."""
    if not text:
        return False
    if rms >= RMS_SILENCE_THRESHOLD and duration_s >= SHORT_DURATION_S:
        return False  # laut genug und lang genug -> echte Sprache

    norm = _normalize(text)
    if norm in PHANTOM_EXACT:
        return True
    return any(p in norm for p in PHANTOM_SUBSTRINGS)
