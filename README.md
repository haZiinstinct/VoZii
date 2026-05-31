# VoZii — Voice-to-Text für Windows

**Lokales Voice-to-Text für Windows 11 — privat, GPU-beschleunigt, in einer einzigen Datei.**

Made by [haZii](https://hazii.org)

---

## Features

- **Push-to-Talk** mit frei wählbarem Hotkey (Tastatur + Maustasten)
- **100% lokal** — keine Cloud, keine API-Keys, keine Daten-Uploads
- **GPU-beschleunigt** — NVIDIA (CUDA), AMD (Vulkan), CPU-Fallback
- **Mehrsprachig** — Deutsch, English, Auto-Detect
- **Drei Modellgrößen** — Tiny (75 MB), Small (465 MB), Medium (1.5 GB)
- **Text wird direkt eingefügt** an der Cursor-Position
- **Clipboard-Fallback** — Text bleibt immer in der Zwischenablage
- **Single-File .exe** (62 MB), keine Installation erforderlich
- **Dark UI** im haZii Corporate Design
- **Nachbearbeitung via Ollama (optional)** — Clean, Format, Prompt-Modi

## Installation

1. **[VoZii.exe herunterladen](https://github.com/haZiinstinct/VoZii/releases/latest)**
2. Doppelklick → Settings-Fenster öffnet sich
3. GPU wird automatisch erkannt, Modell herunterladen (~500 MB beim ersten Start)
4. "Starten" klicken — Tool läuft im System-Tray

> **Windows SmartScreen Warnung?** Das ist normal bei unsignierten .exe-Dateien. Klick auf "Weitere Informationen" → "Trotzdem ausführen". Du kannst auch im Explorer Rechtsklick → Eigenschaften → "Zulassen" → Übernehmen.

## macOS (aus dem Quellcode)

VoZii läuft auf macOS (Apple Silicon + Intel) direkt aus dem Quellcode — es gibt (noch) keine fertige `.app`, du startest über Python. Schnellster Weg: das Setup-Skript.

```bash
bash scripts/setup-macos.sh          # Homebrew-Deps, venv, pip-Pakete
source .venv/bin/activate
python3 src/main.py
```

**Manuell**, falls gewünscht:

```bash
brew install python-tk@3.12 portaudio whisper-cpp   # whisper-cli mit Metal-Beschleunigung
brew install ollama                                  # OPTIONAL, nur für die Nachbearbeitung
python3.12 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python3 src/main.py
```

### Berechtigungen (zwingend)

Ohne diese drei Rechte fürs Terminal (bzw. iTerm) funktioniert der Kern-Loop nicht — **Systemeinstellungen → Datenschutz & Sicherheit:**

| Recht | wofür | Symptom wenn es fehlt |
|---|---|---|
| **Mikrofon** | Aufnahme | leere / keine Transkription |
| **Eingabeüberwachung** | globaler Hotkey (pynput) | Hotkey löst nichts aus |
| **Bedienungshilfen** | Einfügen via Cmd+V (pyautogui) | Text landet nur in der Zwischenablage |

Nach dem Aktivieren das Terminal **komplett beenden und neu starten**.

### Unterschiede zu Windows

- **whisper.cpp** kommt über `brew install whisper-cpp` (Metal-beschleunigtes `whisper-cli`). Das **Sprachmodell** lädt VoZii wie gewohnt in der App herunter.
- Das **Aufnahme-Overlay** ist auf macOS deaktiviert — Start/Stopp wird per **Ton** signalisiert.
- **Autostart** ist auf macOS nicht verfügbar.
- **Menüleisten-Icon:** falls es Probleme macht, in `config.yaml` `show_tray: false` setzen → reiner Hotkey-Modus (Beenden mit `Ctrl+C` im Terminal).
- Zwingend einen **Python mit Tk 8.6** nutzen (Homebrew `python-tk` / python.org), **nicht** das alte System-Python.

## Nutzung

**Push-to-Talk:**
1. Hotkey gedrückt halten (Standard: `Ctrl+Shift+Space`)
2. In das Mikrofon sprechen
3. Hotkey loslassen
4. Text wird an der aktuellen Cursor-Position eingefügt

**Tray-Menü** (Rechtsklick auf das VoZii-Icon unten rechts):
- **Einstellungen** — Hotkey, Sprache, Modell, Mikrofon ändern
- **Log öffnen** — bei Problemen die `vozii.log` anschauen
- **Beenden**

## System-Anforderungen

- **OS:** Windows 11 (64-bit)
- **RAM:** 2 GB frei (4 GB empfohlen für Medium-Modell)
- **GPU:** Optional, beschleunigt Transkription 5-10x
  - NVIDIA GeForce GTX/RTX (CUDA)
  - AMD Radeon RX (Vulkan)
  - Integrierte GPU funktioniert auch
- **CPU-Fallback:** Funktioniert ohne GPU (langsamer)

## Troubleshooting

**Kein Text wird eingefügt?**
→ Tray-Icon → **Log öffnen** → `vozii.log` anschauen

**Mikrofon wird nicht erkannt?**
→ Settings → Mikrofon-Dropdown → anderes Gerät wählen oder "Standard" probieren

**Aufnahme-Fehler?**
→ Das Tool versucht automatisch verschiedene Sample-Rates. Wenn nichts klappt, fallback auf Default-Device.

**Zu langsam?**
→ Settings → Modell → "Tiny" wählen (15-20x schneller als Medium)
→ Oder GPU-Treiber updaten

## Nachbearbeitung via Ollama (optional)

VoZii kann transkribierten Text automatisch korrigieren und formatieren — komplett lokal via [Ollama](https://ollama.com).

**One-Click-Setup direkt aus VoZii:**
1. Settings öffnen → **Nachbearbeitung**
2. Je nach State klickst du einen Button:
   - **"Ollama installieren"** — wenn Ollama fehlt
   - **"Ollama starten"** — wenn installiert, aber nicht gestartet
   - **"Modell laden (2 GB)"** — wenn nur das Modell fehlt
3. Live-Progress mit Speed-Anzeige und **Abbrechen-Button**
4. Fertig — Modi können gewählt werden

**Die 3 Modi:**
- **Aus** — Roher Whisper-Output (Standard)
- **Smart** — Intelligentes Cleanup + context-aware Formatierung + Voice Commands
  - Entfernt Füllwörter und korrigiert Grammatik automatisch
  - Erkennt Voice Commands im gesprochenen Text: *"als Liste"*, *"als Email"*, *"Überschrift"*, *"als Code"*, *"neuer Absatz"*
  - Ohne Command: formatiert intelligent je nach Inhalt (Listen, Absätze, einfache Sätze)
- **Prompt** — verwandelt gesprochenen Text in einen perfekten AI-Prompt

Ohne Ollama funktioniert VoZii normal weiter (Raw Whisper-Output). Bei Fehlern (Ollama nicht erreichbar, Timeout etc.) fällt VoZii automatisch auf den Raw-Text zurück — nie Datenverlust.

**Manuelle Installation** (falls der One-Click-Setup nicht klappt):
- [Ollama herunterladen](https://ollama.com/download)
- Terminal: `ollama pull llama3.2:3b`

## Datenschutz

VoZii läuft **100% lokal** auf deinem Rechner:
- ✅ Keine Audio-Daten werden an Server gesendet
- ✅ Keine Internet-Verbindung im Betrieb nötig (nur für den einmaligen Modell-Download)
- ✅ Keine Telemetrie, keine Analytics
- ✅ Transkribierte Texte bleiben auf deinem Rechner

## Lizenz

Proprietär — siehe [LICENSE](LICENSE) und [THIRDPARTY-LICENSES.md](THIRDPARTY-LICENSES.md) für Dritt-Bibliotheken.

## Kontakt & Support

- **Bug Reports / Feature Requests:** [GitHub Issues](https://github.com/haZiinstinct/VoZii/issues)
- **Website:** [hazii.org](https://hazii.org)
- **E-Mail:** kontakt@hazii.org

---

*VoZii nutzt [whisper.cpp](https://github.com/ggerganov/whisper.cpp) von Georgi Gerganov für lokale Transkription.*
