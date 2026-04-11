# Changelog

Alle relevanten Änderungen an VoZii werden hier dokumentiert.

Format: [Keep a Changelog](https://keepachangelog.com/de/1.1.0/)
Versionierung: [Semantic Versioning](https://semver.org/lang/de/)

---

## [1.4.0] — 2026-04-11

### Changed — Neue Modus-Struktur (Genspark Speakly Style)

**Vorher (4 Modi):** Aus / Clean / Format / Prompt
**Jetzt (3 Modi):** Aus / **Smart** / Prompt

**Warum?** Der Clean-Modus fühlte sich redundant an — Whisper selbst lässt oft schon Füllwörter aus. Der Format-Modus war zu rigide (fixes Markdown). Inspiriert von [Genspark Speakly](https://speakly.ai/) haben wir beide zu einem intelligenten **Smart-Modus** zusammengefasst.

### Neu: Smart-Modus

Ein einziger intelligenter Modus der alles kann:
- Füllwörter entfernen + Grammatik korrigieren
- **Context-aware Formatierung** — erkennt automatisch ob der Text eine Liste, Absätze oder ein einfacher Satz sein soll
- **Voice Commands erkennen** — sag "als Liste", "als Email", "Überschrift", "als Code", "neuer Absatz" und der Smart-Modus befolgt den Command (und entfernt ihn aus dem Output!)

**Beispiele:**
- *"ähm ich wollte halt sagen dass das tool super funktioniert"* → "Ich wollte sagen, dass das Tool super funktioniert."
- *"ich brauche folgende zutaten als Liste mehl zucker butter eier"* → Bullet-Liste mit Mehl, Zucker, Butter, Eier (ohne "als Liste")
- *"schreibe als Email an Tom dass wir morgen treffen"* → formeller Email-Text
- *"Überschrift Projektplan Q2 dann darunter eine Liste mit meilensteinen"* → `# Projektplan Q2` + Liste

### Migration

Alte Config-Werte werden **automatisch migriert**: wenn `post_processing_mode: clean` oder `format` → wird auf `smart` gesetzt und in der config.yaml gespeichert. Kein manuelles Eingreifen nötig.

---

## [1.3.2] — 2026-04-11

### Fixed
- **Layout-Shift beim Ollama-Start:** Klick auf Mini-Button "▶" triggerte das große Download-UI (100px hoch), die gesamte Settings-Anzeige rutschte nach unten. Jetzt wird beim Start nur der Status-Text aktualisiert, kein Layout-Shift.
- **Overlay-Indikator "hängt" während Post-Processing:** Wenn Ollama den Text verarbeitet (kann bei großen Texten mehrere Sekunden dauern), blieb das Overlay statisch auf "· · ·" stehen. Jetzt animiert das Overlay die Dots (Zyklus: · → · · → · · · → · ·) alle 300ms, zeigt klar dass das Tool noch arbeitet.

### Changed
- `_handle_ollama_start()` nutzt nicht mehr `_ollama_busy = True` — der Start ist keine Download-Operation und braucht kein Download-UI
- `RecordingOverlay._apply()` startet Animation-Loop bei TRANSCRIBING state

---

## [1.3.1] — 2026-04-11

### Fixed
- **Kritisch: Tool startete nicht mehr nach Klick auf "Starten"** — `_save()` referenzierte `self._ollama_running` und `self._ollama_models`, die in v1.3.0 durch `self._ollama_state` ersetzt wurden. AttributeError crashte den Save-Callback stumm, Settings-Fenster schloss sich aber Tool lief nicht.

### Added
- **Start/Stop Mini-Button** rechts neben dem Ollama-Status:
  - `▶` (Start) wenn Ollama installiert aber nicht gestartet
  - `■` (Stop) wenn Ollama läuft (egal ob Modell da ist)
  - Hover-Farbe: Grün für Start, Rot für Stop
- `stop_ollama()` in `text_processor.py` — beendet "ollama app.exe" + "ollama.exe" via taskkill

### Changed
- State `installed_not_running`: Kein großer "Ollama starten" Button mehr, stattdessen der kompakte Mini-Button (weniger Redundanz)

---

## [1.3.0] — 2026-04-11

### Added
- **4-State Ollama-Erkennung** statt 3 States:
  - `ready` — Ollama läuft, Modell da
  - `no_model` — Ollama läuft, Modell fehlt → Button "Modell laden"
  - `installed_not_running` — **NEU!** Ollama installiert, nicht gestartet → Button "Ollama starten"
  - `not_installed` — Ollama nicht installiert → Button "Ollama installieren"
- `is_ollama_installed()` in `text_processor.py` — erkennt Ollama via `shutil.which()` + bekannte Install-Pfade (`%LOCALAPPDATA%\Programs\Ollama`)
- `start_ollama()` in `text_processor.py` — startet die GUI-App (bevorzugt) oder `ollama serve`, pollt API bis erreichbar
- **Cancel-Button während Install/Pull** — immer sichtbar, bricht Download graceful ab (löscht temp Dateien)
- **Verbesserte Download-Anzeige:**
  - Große Prozent-Anzeige (20px Mono, Cyan)
  - Dickere Progress-Bar (8px statt 4px)
  - Live Speed (MB/s) alle 200ms aktualisiert
  - Detail-Zeile: "650 MB / 2048 MB · 12.3 MB/s · Status"

### Changed
- `install_ollama()` und `pull_model()` akzeptieren jetzt `cancel_event` Parameter (threading.Event)
- Chunked Download statt `urlretrieve()` für Cancel-Support + Speed-Tracking
- UI-Widget `ollama_dl_frame` als dedicated Download-Container

### Fixed
- Wenn Ollama installiert ist aber nicht läuft, wird VoZii nicht mehr fälschlicherweise "nicht installiert" zeigen
- Abgebrochene Downloads hinterlassen keine `.part` Dateien mehr

---

## [1.2.0] — 2026-04-11

### Added
- **One-Click Ollama Setup** — kein Terminal, kein manueller Download
  - Smart Nachbearbeitungs-Section mit 3 States
  - **Nicht installiert:** Button "Ollama einrichten (3 GB gesamt)" lädt Installer, startet ihn, wartet bis API bereit, lädt Modell
  - **Modell fehlt:** Button "Modell herunterladen (2 GB)" nutzt Ollama Pull API mit Streaming-Progress
  - **Bereit:** Status "● Ollama bereit · llama3.2:3b"
  - Live Progress-Bar während Install/Pull
- `install_ollama()` in `text_processor.py` — Auto-Download + Auto-Start des Windows-Installers
- `pull_model()` in `text_processor.py` — nutzt `POST /api/pull` mit Streaming für Live-Progress
- `get_ollama_state()` — zentrale State-Detection

### Changed (Multi-Hardware Robustness)
- **`hardware.py`**: PowerShell-Fallback via `Get-CimInstance Win32_VideoController`
  - Fixt Systeme auf neueren Windows 11 Builds wo `wmic` deprecated/nicht installiert ist
  - Intel GPUs werden explizit als CPU-Fallback behandelt (mit Log-Info)
- **`paths.py`**: Schreibbarkeits-Check + Fallback auf `%LOCALAPPDATA%\VoZii`
  - Fixt Installation in read-only Ordnern (`C:\Program Files\`, OneDrive, etc.)
  - `config.yaml`, `vozii.log`, `whisper-cpp/` landen automatisch in `%LOCALAPPDATA%\VoZii` wenn .exe-Ordner nicht schreibbar

### Technical
- Keine neue Dependency — `urllib.request`, `subprocess`, `tempfile` (alles stdlib)
- Ollama-Installer: `https://ollama.com/download/OllamaSetup.exe` (kein Admin nötig)
- Installer-Timeout: 180s (für langsame Systeme)
- Progress-Updates thread-safe via `root.after(0, ...)`

---

## [1.1.0] — 2026-04-11

### Added
- **Text Post-Processing via Ollama** (optional, komplett lokal)
  - **Clean** Mode: Entfernt Füllwörter, korrigiert Grammatik und Interpunktion
  - **Format** Mode: Clean + Markdown-Struktur (Überschriften, Listen, Fettschrift)
  - **Prompt** Mode: Verwandelt gesprochenen Text in einen perfekten AI-Prompt
  - **Aus** Mode: Raw Whisper-Output (Standard)
- Neue Settings-Section "Nachbearbeitung" mit Live-Status-Anzeige
  - "● Ollama bereit · modellname" wenn Ollama läuft
  - "○ Ollama nicht gefunden" wenn nicht erreichbar (Section disabled)
- `src/text_processor.py` — TextProcessor-Klasse + Ollama HTTP-Integration
- Automatischer Fallback auf Raw-Text wenn Ollama-Call fehlschlägt

### Changed
- Settings-Fenster höher (580 → 680 px) für die neue Section
- README.md: Section "Nachbearbeitung (optional)" mit Ollama-Setup-Anleitung

### Technical
- Keine neue Dependency: Ollama-Integration nutzt `urllib.request` (stdlib)
- Ollama läuft auf `http://localhost:11434`
- Default-Modell: `llama3.2:3b` (~2 GB, schnell mit GPU)

---

## [1.0.0] — 2026-04-10

### Initial Release

**Core Features:**
- Voice-to-Text via [whisper.cpp](https://github.com/ggerganov/whisper.cpp)
- Push-to-Talk Hotkey mit Tastatur- und Maustasten-Support
- Toggle-Mode als Alternative
- Mehrsprachig: Deutsch, English, Auto-Detect
- Whisper-Modelle: Tiny, Small, Medium

**Hardware:**
- Auto-Detection NVIDIA (CUDA) / AMD (Vulkan) / CPU (BLAS)
- DirectSound Mikrofon-Auswahl mit automatischem Fallback
- Sample-Rate Resampling via scipy (48 kHz → 16 kHz für Whisper)

**UI / UX:**
- haZii Corporate Design (Dark Mode, Cyan Akzent)
- Borderless draggable Settings-Fenster
- CustomTkinter Komponenten
- System Tray mit dynamischem Icon
- Recording-Overlay (schlank, unsichtbar in Taskbar)
- Modell-Download mit Progress-Bar direkt in der GUI

**Reliability:**
- Single-Instance Lock via `msvcrt.locking`
- RotatingFileHandler Logging zu `vozii.log`
- `sys.excepthook` + `threading.excepthook` für stumme Thread-Exceptions
- Download-Resume für abgebrochene Modell-Downloads
- Modell-Integritätsprüfung (Datei-Größe)
- Exception-Handling in allen kritischen Pfaden

**Distribution:**
- Single-File .exe (62 MB) via PyInstaller
- Keine Installation erforderlich
- whisper.cpp + Modell werden beim ersten Start heruntergeladen
- Windows Auto-Start Option (Registry)

### Lizenz
Proprietär. Siehe [LICENSE](LICENSE).
