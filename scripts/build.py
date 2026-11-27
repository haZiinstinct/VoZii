"""VoZii Build — eine einzige schlanke standalone .exe."""

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

# Generierte Spec: schlankes Filtern spart ~10 MB Exe-Groesse und ~600 Dateien
# beim Onefile-Entpacken (schnellerer Kaltstart):
# - PIL: VoZii zeichnet nur ein 64x64-Tray-Icon -> kein _avif (4,1 MB), _webp, _imagingcms
# - onnx_asr: Parakeet auf CPU nutzt NemoPreprocessorNumpy (fbanks.npz) -> keine
#   28 ungenutzten whisper/kaldi/gigaam/nemo80/resample-ONNX-Dateien (~3,6 MB)
# - _sounddevice_data: keine 32-Bit-PortAudio-DLL auf x64
# - _tcl_data/_tk_data: keine tzdata/msgs/demos (~600 Einzeldateien)
_SPEC_TEMPLATE = """\
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

BASE = {base_dir!r}
VERSION_FILE = {version_file!r}

datas = [
    (BASE + '/assets/fonts', 'assets/fonts'),
    (BASE + '/src/vozii.ico', 'src'),
]
binaries = []
hiddenimports = [
    'tkinter', 'tkinter.ttk', 'tkinter.messagebox',
    'pynput.keyboard._win32', 'pynput.mouse._win32',
    'PIL._tkinter_finder',
]

datas += collect_data_files('onnx_asr')
datas += copy_metadata('onnx-asr')
datas += copy_metadata('onnxruntime')
binaries += collect_dynamic_libs('onnxruntime')
hiddenimports += collect_submodules('pynput')
hiddenimports += collect_submodules('onnx_asr')

for pkg in ('customtkinter', 'tkinter'):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

excludes = [
    'pyperclip', 'unittest', 'pydoc', 'doctest', 'test', 'tkinter.test',
    'sqlite3', 'xmlrpc', 'ftplib', 'imaplib', 'poplib', 'smtplib',
    'telnetlib', 'turtle', 'turtledemo', 'scipy', 'matplotlib', 'pytest',
    'numpy.testing', 'numpy.f2py',
    'PIL.AvifImagePlugin', 'PIL.WebPImagePlugin', 'PIL.ImageCms',
    'PIL.PdfImagePlugin', 'PIL.PsdImagePlugin', 'PIL.TiffImagePlugin',
    'PIL.Jpeg2KImagePlugin', 'PIL.ImageMorph', 'PIL.ImageMath',
]

a = Analysis(
    [BASE + '/src/main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=1,
)


def _keep_binary(entry):
    name = entry[0].replace('\\\\', '/').lower()
    if any(drop in name for drop in (
        'pil/_avif', 'pil/_webp', 'pil/_imagingcms', 'pil/_imagingmorph',
        'pil/_imagingmath', 'libportaudio32bit',
    )):
        return False
    return True


def _keep_data(entry):
    name = entry[0].replace('\\\\', '/').lower()
    if 'onnx_asr/preprocessors/data/' in name:
        fname = name.rsplit('/', 1)[-1]
        return fname in ('fbanks.npz', 'nemo128.onnx')
    if name.startswith('_tcl_data/tzdata/') or name.startswith('_tcl_data/msgs/'):
        return False
    if name.startswith('_tk_data/demos/') or name.startswith('_tk_data/msgs/'):
        return False
    if 'libportaudio32bit' in name:
        return False
    return True


a.binaries = [b for b in a.binaries if _keep_binary(b)]
a.datas = [d for d in a.datas if _keep_data(d)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='VoZii',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=VERSION_FILE,
    icon=[BASE + '/src/vozii.ico'],
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


def _write_spec_file(version_file: str) -> str:
    out_dir = os.path.join(BASE_DIR, "build")
    os.makedirs(out_dir, exist_ok=True)
    spec_path = os.path.join(out_dir, "VoZii.spec")
    content = _SPEC_TEMPLATE.format(
        base_dir=BASE_DIR.replace("\\", "/"),
        version_file=version_file.replace("\\", "/"),
    )
    with open(spec_path, "w", encoding="utf-8") as f:
        f.write(content)
    return spec_path


def build(dist_dir: str | None = None):
    """dist_dir: Zielordner (Default dist/). dist/ ist oft eine laufende
    portable Installation — zum Testen woanders hin bauen."""
    dist_dir = os.path.abspath(dist_dir or os.path.join(BASE_DIR, "dist"))
    print("=" * 40)
    print("  VoZii — Build (Single .exe)")
    print("=" * 40)

    version_file = _write_version_file()
    spec_file = _write_spec_file(version_file)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--distpath", dist_dir,
        "--workpath", os.path.join(BASE_DIR, "build"),
        "--clean",
        spec_file,
    ]

    result = subprocess.run(cmd, cwd=BASE_DIR)
    if result.returncode != 0:
        print("[FEHLER] Build fehlgeschlagen!")
        sys.exit(1)

    exe_path = os.path.join(dist_dir, "VoZii.exe")
    if os.path.isfile(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"\n  Fertig: {exe_path}")
        print(f"  Groesse: {size_mb:.1f} MB")
        print("\n  Diese eine Datei an Kollegen schicken!")
        print("  whisper-cpp + Modell werden beim ersten Start geladen.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="VoZii als Single-Exe bauen")
    parser.add_argument("--distpath", help="Zielordner (Default: dist/)")
    build(parser.parse_args().distpath)
