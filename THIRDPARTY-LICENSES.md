# Third-Party Licenses

VoZii verwendet folgende Open-Source-Bibliotheken und Binaries.
Alle bleiben unter ihrer jeweiligen Lizenz.

---

## Whisper Engine

### whisper.cpp
- **Autor:** Georgi Gerganov
- **Lizenz:** MIT License
- **URL:** https://github.com/ggml-org/whisper.cpp
- **Nutzung:** Lokale Whisper-Inference (als Subprocess aufgerufen); der
  Vulkan-Build für AMD-GPUs wird seit v1.8 selbst aus dem Upstream-Source gebaut
  (`.github/workflows/build-backend.yml`)

### GGML Whisper Models
- **Autor:** OpenAI (trained) / ggerganov (converted)
- **Lizenz:** MIT License
- **URL:** https://huggingface.co/ggerganov/whisper.cpp

---

## Parakeet Engine (CPU)

### NVIDIA Parakeet TDT 0.6B v3
- **Autor:** NVIDIA
- **Lizenz:** CC BY 4.0
- **URL:** https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
- **Nutzung:** Spracherkennungsmodell der Parakeet-Engine; wird bei Bedarf als
  ONNX-Export (int8) von https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx
  (CC BY 4.0) heruntergeladen, unverändert

### onnx-asr
- **Autor:** Ilya Stupakov
- **Lizenz:** MIT License
- **URL:** https://github.com/istupakov/onnx-asr

### ONNX Runtime
- **Autor:** Microsoft
- **Lizenz:** MIT License
- **URL:** https://github.com/microsoft/onnxruntime
- **Abhängigkeiten:** flatbuffers (Apache 2.0), protobuf (BSD 3-Clause)

---

## Python Libraries

### customtkinter
- **Autor:** Tom Schimansky
- **Lizenz:** MIT License
- **URL:** https://github.com/TomSchimansky/CustomTkinter

### pynput
- **Autor:** Moses Palmer
- **Lizenz:** GNU LGPL v3
- **URL:** https://github.com/moses-palmer/pynput
- **Hinweis:** LGPL erlaubt die Nutzung in proprietärer Software, solange die
  Library dynamisch gelinkt ist. VoZii nutzt pynput als Python-Package-Import.

### sounddevice
- **Autor:** Matthias Geier
- **Lizenz:** MIT License
- **URL:** https://github.com/spatialaudio/python-sounddevice

### numpy
- **Lizenz:** BSD 3-Clause
- **URL:** https://numpy.org

### Pillow (PIL)
- **Lizenz:** HPND (Historical Permission Notice and Disclaimer)
- **URL:** https://python-pillow.org

### PyYAML
- **Autor:** Kirill Simonov
- **Lizenz:** MIT License
- **URL:** https://pyyaml.org

### pystray
- **Autor:** Moses Palmer
- **Lizenz:** LGPL v3
- **URL:** https://github.com/moses-palmer/pystray

### pyperclip
- **Autor:** Al Sweigart
- **Lizenz:** BSD 3-Clause
- **URL:** https://github.com/asweigart/pyperclip
- **Hinweis:** nur noch Fallback ausserhalb von Windows; unter Windows nutzt
  VoZii die Zwischenablage direkt ueber die Win32-API (`src/winclip.py`).

---

## Runtime

### Python 3.12 (Release-Build)
- **Lizenz:** PSF License
- **URL:** https://www.python.org

### PyInstaller (Build Tool)
- **Lizenz:** GPL + Bootloader Exception (erlaubt proprietäre Distribution)
- **URL:** https://www.pyinstaller.org

---

## Fonts

Gebuendelt unter `assets/fonts/`, zur Laufzeit privat geladen (keine
Installation). Fallback auf Windows System Fonts (Segoe UI, Consolas).

### Inter
- **Autor:** Rasmus Andersson
- **Lizenz:** SIL Open Font License 1.1
- **URL:** https://github.com/rsms/inter

### JetBrains Mono
- **Autor:** JetBrains
- **Lizenz:** SIL Open Font License 1.1
- **URL:** https://github.com/JetBrains/JetBrainsMono

---

## Hinweis zur Kommerzialisierung

Bei kommerzieller Verteilung sollten die LGPL-Abhängigkeiten (pynput, pystray)
rechtlich geprüft werden. Die LGPL erlaubt die Nutzung in proprietärer Software
unter bestimmten Bedingungen, aber Details sollten im Einzelfall geklärt werden.

Für Fragen: kontakt@hazii.org
