"""Windows-spezifische ctypes-Helfer (Dark-Titlebar, Job-Object).

Alles still no-op ausserhalb von Windows, damit der restliche Code
plattformneutral bleibt.
"""

import ctypes
import logging
import sys

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

# DWMWA_USE_IMMERSIVE_DARK_MODE: 20 ab Win10 20H1/Win11, 19 auf aelteren Builds
_DWMWA_DARK = 20
_DWMWA_DARK_OLD = 19

# Job-Object: Server stirbt automatisch, wenn das letzte Handle (= unser
# Prozess) schliesst — auch bei Crash/Force-Kill. Kein verwaister whisper-server.
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JobObjectExtendedLimitInformation = 9


def enable_dark_titlebar(root) -> None:
    """Faerbt die native Titelleiste eines Tk-Fensters dunkel (Win11/aktuelles Win10)."""
    if not IS_WINDOWS:
        return
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1)
        for attr in (_DWMWA_DARK, _DWMWA_DARK_OLD):
            res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
            if res == 0:
                return
    except Exception:
        log.debug("Dark-Titlebar nicht setzbar", exc_info=True)


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def create_kill_on_close_job():
    """Erzeugt ein Job-Object, das alle zugewiesenen Prozesse killt, sobald das
    Handle schliesst (Prozessende). Returns das Handle oder None.

    Das Handle MUSS am Leben gehalten werden (Referenz speichern), sonst greift
    die Kill-on-close-Semantik sofort.
    """
    if not IS_WINDOWS:
        return None
    try:
        job = ctypes.windll.kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = ctypes.windll.kernel32.SetInformationJobObject(
            job, _JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info))
        if not ok:
            ctypes.windll.kernel32.CloseHandle(job)
            return None
        return job
    except Exception:
        log.debug("Job-Object nicht erstellbar", exc_info=True)
        return None


def assign_process_to_job(job, pid: int) -> bool:
    """Weist den Prozess (pid) dem Job zu. Returns True bei Erfolg."""
    if not IS_WINDOWS or not job:
        return False
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001
    try:
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not handle:
            return False
        try:
            return bool(ctypes.windll.kernel32.AssignProcessToJobObject(job, handle))
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        log.debug("AssignProcessToJobObject fehlgeschlagen", exc_info=True)
        return False
