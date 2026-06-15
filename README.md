# VoZii — Voice-to-Text für Windows

**Lokales Voice-to-Text für Windows 11 — privat, GPU-beschleunigt, in einer einzigen Datei.**

Made by [haZii](https://hazii.org)

---

## Features

- **Push-to-Talk** mit frei wählbarem Hotkey (Tastatur + Maustasten)
- **100% lokal** — keine Cloud, keine API-Keys, keine Daten-Uploads
- **Schnell** — das Whisper-Modell bleibt im RAM (whisper-server), keine Ladezeit pro Diktat
- **GPU-beschleunigt** — NVIDIA (CUDA), AMD (Vulkan), CPU-Fallback
- **Mehrsprachig** — Deutsch, English, Auto-Detect
- **Effektive Whisper-Modelle** — Schnell (Tiny, 75 MB), Empfohlen (large-v3-turbo, 550 MB), Beste (large-v3-turbo HQ, 1.5 GB)
- **Text wird direkt eingefügt** an der Cursor-Position; die vorherige Zwischenablage wird danach wiederhergestellt
- **Transkriptions-Historie** — die letzten Diktate über das Tray-Menü wieder kopierbar
- **Schnell/Genau-Modus** — greedy für flottes Diktat oder Beam-Search für maximale Genauigkeit
- **Single-File .exe** (32 MB), keine Installation erforderlich
- **Dark UI** im haZii Corporate Design (Inter + JetBrains Mono)
- **Nachbearbeitung via Ollama (optional)** — Smart- und Prompt-Modus
- **Verifizierte Downloads** — Modelle und Binaries werden gegen SHA256-Checksummen geprüft

## Installation

1. **[VoZii.exe herunterladen](https://github.com/haZiinstinct/VoZii/releases/latest)**
2. Doppelklick → Settings-Fenster öffnet sich
3. GPU wird automatisch erkannt, Modell herunterladen (~500 MB beim ersten Start)
4. Optional: **Mikrofon testen** (Settings → Testen) — Pegelanzeige zeigt sofort, ob alles passt
5. "Starten" klicken — Tool läuft im System-Tray

> **Datenablage:** Modelle, Config und Log liegen unter `%LOCALAPPDATA%\VoZii`
> (Bestandsinstallationen mit Daten neben der .exe werden weiter dort genutzt).

> **Windows SmartScreen Warnung?** Das ist normal bei unsignierten .exe-Dateien. Klick auf "Weitere Informationen" → "Trotzdem ausführen". Du kannst auch im Explorer Rechtsklick → Eigenschaften → "Zulassen" → Übernehmen.

## Nutzung

**Push-to-Talk:**
1. Hotkey gedrückt halten (Standard: `Ctrl+Shift+Space`)
2. In das Mikrofon sprechen
3. Hotkey loslassen
4. Text wird an der aktuellen Cursor-Position eingefügt

**Tray-Menü** (Rechtsklick auf das VoZii-Icon unten rechts):
- **Letzte Transkriptionen** — die letzten 5 Diktate, Klick kopiert den Volltext
- **Einstellungen** — Hotkey, Sprache, Modell, Mikrofon ändern
- **Log öffnen** — bei Problemen die `vozii.log` anschauen
- **Beenden**

**Status-Anzeige** (unten rechts, auf dem Monitor mit der Maus):
- `● REC` — Aufnahme läuft, `· · ·` — transkribiert
- `CLIP` — Einfügen ging nicht, der Text liegt in der Zwischenablage
- `SHORT` / `LEER` — Aufnahme zu kurz bzw. nichts erkannt
- `ERR:MIC` / `ERR:WHISPER` — Fehlerquelle (Details in `vozii.log`)

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
→ Zeigt das Overlay `CLIP`, liegt der Text in der Zwischenablage (kein Textfeld fokussiert)
→ Oder über Tray → **Letzte Transkriptionen** wieder kopieren
→ Details: Tray-Icon → **Log öffnen** → `vozii.log`

**Mikrofon wird nicht erkannt?**
→ Settings → **Testen** klicken — die Pegelanzeige zeigt, ob Signal ankommt
→ Anderes Gerät im Dropdown wählen oder "Standard" probieren

**Zu langsam?**
→ Settings → Transkription → **Schnell** (greedy statt Beam-Search)
→ Settings → Modell → "Schnell" wählen (deutlich schneller)
→ Oder GPU-Treiber updaten

**Windows zeigt dauerhaft das Mikrofon-Symbol?**
→ Normal: VoZii hält den Audio-Stream offen, damit beim Hotkey-Druck keine
  erste Silbe verloren geht. Aufgenommen wird nur, solange der Hotkey gedrückt ist.

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
- Terminal: `ollama pull qwen2.5:3b` (oder `llama3.2:1b` / `gemma3:4b`)

## Datenschutz

VoZii läuft **100% lokal** auf deinem Rechner:
- ✅ Keine Audio-Daten werden an Server gesendet
- ✅ Keine Internet-Verbindung im Betrieb nötig (nur für den einmaligen Modell-Download)
- ✅ Keine Telemetrie, keine Analytics
- ✅ Transkribierte Texte bleiben auf deinem Rechner
- ✅ Die Transkriptions-Historie (letzte 50) liegt lokal in `history.json`
  unter dem VoZii-Datenordner — in den Settings abschaltbar und löschbar

## Lizenz

Proprietär — siehe [LICENSE](LICENSE) und [THIRDPARTY-LICENSES.md](THIRDPARTY-LICENSES.md) für Dritt-Bibliotheken.

## Kontakt & Support

- **Bug Reports / Feature Requests:** [GitHub Issues](https://github.com/haZiinstinct/VoZii/issues)
- **Website:** [hazii.org](https://hazii.org)
- **E-Mail:** kontakt@hazii.org

---

*VoZii nutzt [whisper.cpp](https://github.com/ggerganov/whisper.cpp) von Georgi Gerganov für lokale Transkription.*
