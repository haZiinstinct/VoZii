"""Windows-Fehlercode-Klassifikation + Systemvoraussetzungs-Checks.

Uebersetzt kryptische Prozess-Exit-Codes der whisper-Binaries in
verstaendliche Hinweise (Smart-App-Control-Block, fehlende VC++-Runtime)
und prueft die VC++-Runtime, die alle whisper.cpp-Binaries brauchen.
"""

import ctypes
import logging

log = logging.getLogger(__name__)

VCREDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"

# NTSTATUS-Codes, mit denen whisper-Prozesse auf fremden Systemen sterben.
# 0xC0E90002 = STATUS_SYSTEM_INTEGRITY_POLICY_VIOLATION: Smart App Control /
# WDAC verweigert das Laden der unsignierten DLL (real diagnostizierter Fall).
_EXIT_CODE_HINTS = {
    0xC0000135: "err.hint.vcredist",  # STATUS_DLL_NOT_FOUND
    0xC0E90002: "err.hint.sac",
    0xC0000409: "err.hint.crash",     # Fast-Fail / Stack-Check
    0xC0000005: "err.hint.crash",     # Access Violation
}


def classify_win_exit_code(code: int) -> str | None:
    """i18n-Key mit Erklaerung fuer einen Prozess-Exit-Code, sonst None.

    subprocess liefert Exit-Codes je nach Pfad signed oder unsigned —
    beides auf 32-Bit-unsigned normalisieren."""
    return _EXIT_CODE_HINTS.get(code & 0xFFFFFFFF)


_LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x00000800


def check_vcredist() -> bool:
    """Ist die VC++-2015-2022-Runtime systemweit installiert?

    Bewusst LoadLibraryExW mit SEARCH_SYSTEM32 statt ctypes.WinDLL: die
    onefile-Exe bringt eigene Kopien in %TEMP%\\_MEI... mit, die das Ergebnis
    verfaelschen wuerden — die whisper-Binaries laufen ausserhalb davon und
    sehen nur System32."""
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p,
                                            ctypes.c_uint32]
        kernel32.LoadLibraryExW.restype = ctypes.c_void_p
        kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
        for dll in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
            handle = kernel32.LoadLibraryExW(dll, None, _LOAD_LIBRARY_SEARCH_SYSTEM32)
            if not handle:
                log.warning("VC++-Runtime-DLL fehlt in System32: %s", dll)
                return False
            kernel32.FreeLibrary(handle)
        return True
    except Exception:
        # Check darf den Start nie verhindern — im Zweifel "vorhanden"
        log.exception("VC++-Check fehlgeschlagen — nehme 'vorhanden' an")
        return True
