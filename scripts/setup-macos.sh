#!/usr/bin/env bash
# VoZii — macOS Setup (aus Quellcode lauffaehig machen).
#
# Installiert die System-Abhaengigkeiten via Homebrew, legt ein virtuelles
# Environment an und installiert die Python-Pakete.
# Danach:  source .venv/bin/activate && python3 src/main.py
set -euo pipefail

# Ins Projekt-Root wechseln (dieses Skript liegt in scripts/)
cd "$(dirname "$0")/.."

echo "==> VoZii macOS Setup"

# 1. Homebrew vorhanden?
if ! command -v brew >/dev/null 2>&1; then
  echo "FEHLER: Homebrew nicht gefunden. Installiere es von https://brew.sh" >&2
  exit 1
fi

# 2. System-Pakete: Tk-8.6-Python, PortAudio, whisper.cpp (liefert whisper-cli mit Metal)
echo "==> Installiere System-Pakete (python-tk@3.12, portaudio, whisper-cpp)"
brew install python-tk@3.12 portaudio whisper-cpp
echo "    (Optional fuer die Nachbearbeitung:  brew install ollama)"

# 3. Python waehlen (bevorzugt das frische brew-Python mit Tk 8.6)
PY="$(command -v python3.12 || command -v python3.11 || command -v python3)"
echo "==> Nutze Python: $PY ($("$PY" --version 2>&1))"

# 4. Virtuelles Environment
if [ ! -d .venv ]; then
  echo "==> Erstelle virtuelle Umgebung (.venv)"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 5. Python-Pakete
echo "==> Installiere Python-Pakete (inkl. pyobjc fuer macOS)"
python -m pip install --upgrade pip
pip install -r requirements.txt

cat <<'EOF'

==> Setup fertig.

Noch erforderlich: Berechtigungen fuer dein Terminal unter
Systemeinstellungen -> Datenschutz & Sicherheit:
  * Mikrofon
  * Eingabeueberwachung   (globaler Hotkey)
  * Bedienungshilfen      (Cmd+V einfuegen)
Danach das Terminal komplett neu starten.

Starten:
  source .venv/bin/activate
  python3 src/main.py
EOF
