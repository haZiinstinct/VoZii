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

## Installation

1. **[VoZii.exe herunterladen](https://github.com/haZiinstinct/VoZii/releases/latest)**
2. Doppelklick → Settings-Fenster öffnet sich
3. GPU wird automatisch erkannt, Modell herunterladen (~500 MB beim ersten Start)
4. "Starten" klicken — Tool läuft im System-Tray

> **Windows SmartScreen Warnung?** Das ist normal bei unsignierten .exe-Dateien. Klick auf "Weitere Informationen" → "Trotzdem ausführen". Du kannst auch im Explorer Rechtsklick → Eigenschaften → "Zulassen" → Übernehmen.

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
