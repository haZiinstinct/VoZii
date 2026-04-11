# Changelog

Alle relevanten Änderungen an VoZii werden hier dokumentiert.

Format: [Keep a Changelog](https://keepachangelog.com/de/1.1.0/)
Versionierung: [Semantic Versioning](https://semver.org/lang/de/)

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
