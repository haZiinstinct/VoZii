"""VoZii Build — eine einzige standalone .exe."""

import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# Windows-Versionsressource (Datei-Eigenschaften der .exe). Fehlte frueher
# komplett — eine Exe ohne Produktname/Company triggert AV-/SmartScreen-
# Heuristiken zusaetzlich.
_VERSION_INFO = """\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={vers}, prodvers={vers},
    mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'haZii.org'),
      StringStruct('FileDescription', 'VoZii — Voice-to-Text'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'VoZii'),
      StringStruct('LegalCopyright', '(c) 2026 haZii.org'),
      StringStruct('OriginalFilename', 'VoZii.exe'),
      StringStruct('ProductName', 'VoZii'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def _write_version_file() -> str:
    from src import __version__

    parts = [int(p) for p in __version__.split(".")]
    vers = tuple((parts + [0, 0, 0, 0])[:4])
    out_dir = os.path.join(BASE_DIR, "build")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "version_info.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_VERSION_INFO.format(vers=vers, version=__version__))
    return path


def build():
    print("=" * 40)
    print("  VoZii — Build (Single .exe)")
    print("=" * 40)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",                  # Cache loeschen fuer sauberen Build
        "--onefile",                # EINE .exe
        "--windowed",               # Keine Konsole
        "--noupx",                  # UPX = bekannter AV-Falsch-Positiv-Trigger
        "--version-file", _write_version_file(),
        "--name", "VoZii",
        "--icon", os.path.join(BASE_DIR, "src", "vozii.ico"),
        "--add-data", f"{os.path.join(BASE_DIR, 'config.default.yaml')};.",
        "--add-data", f"{os.path.join(BASE_DIR, 'assets', 'fonts')};assets/fonts",
        "--add-data", f"{os.path.join(BASE_DIR, 'src', 'vozii.ico')};src",
        # tkinter — wird von customtkinter UND settings_gui.py gebraucht
        "--hidden-import", "tkinter",
        "--hidden-import", "tkinter.ttk",
        "--hidden-import", "tkinter.messagebox",
        "--hidden-import", "pynput.keyboard._win32",
        "--hidden-import", "pynput.mouse._win32",
        "--hidden-import", "PIL._tkinter_finder",
        "--collect-submodules", "pynput",
        "--collect-all", "customtkinter",
        "--collect-all", "tkinter",
        os.path.join(BASE_DIR, "src", "main.py"),
    ]

    result = subprocess.run(cmd, cwd=BASE_DIR)
    if result.returncode != 0:
        print("[FEHLER] Build fehlgeschlagen!")
        sys.exit(1)

    exe_path = os.path.join(BASE_DIR, "dist", "VoZii.exe")
    if os.path.isfile(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"\n  Fertig: {exe_path}")
        print(f"  Groesse: {size_mb:.0f} MB")
        print(f"\n  Diese eine Datei an Kollegen schicken!")
        print(f"  whisper-cpp + Modell werden beim ersten Start geladen.")


if __name__ == "__main__":
    build()
