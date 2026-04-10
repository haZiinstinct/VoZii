# Third-Party Licenses

VoZii verwendet folgende Open-Source-Bibliotheken und Binaries.
Alle bleiben unter ihrer jeweiligen Lizenz.

---

## Whisper Engine

### whisper.cpp
- **Autor:** Georgi Gerganov
- **Lizenz:** MIT License
- **URL:** https://github.com/ggerganov/whisper.cpp
- **Nutzung:** Lokale Whisper-Inference (als Subprocess aufgerufen)

### whisper.cpp Vulkan Build (AMD GPUs)
- **Autor:** Jerry Shell
- **Lizenz:** MIT License
- **URL:** https://github.com/jerryshell/whisper.cpp-windows-vulkan-bin
- **Nutzung:** Pre-built Binary für AMD RDNA Vulkan-Beschleunigung

### GGML Whisper Models
- **Autor:** OpenAI (trained) / ggerganov (converted)
- **Lizenz:** MIT License
- **URL:** https://huggingface.co/ggerganov/whisper.cpp

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

### scipy
- **Lizenz:** BSD 3-Clause
- **URL:** https://scipy.org

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

### PyAutoGUI
- **Autor:** Al Sweigart
- **Lizenz:** BSD 3-Clause
- **URL:** https://github.com/asweigart/pyautogui

---

## Runtime

### Python 3.14
- **Lizenz:** PSF License
- **URL:** https://www.python.org

### PyInstaller (Build Tool)
- **Lizenz:** GPL + Bootloader Exception (erlaubt proprietäre Distribution)
- **URL:** https://www.pyinstaller.org

---

## Fonts

VoZii verwendet keine custom Fonts. Die UI nutzt Windows System Fonts
(Segoe UI, Consolas).

---

## Hinweis zur Kommerzialisierung

Bei kommerzieller Verteilung sollten die LGPL-Abhängigkeiten (pynput, pystray)
rechtlich geprüft werden. Die LGPL erlaubt die Nutzung in proprietärer Software
unter bestimmten Bedingungen, aber Details sollten im Einzelfall geklärt werden.

Für Fragen: kontakt@hazii.org
