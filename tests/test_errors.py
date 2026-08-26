"""Fehlercode-Klassifikation (SAC/VC++/Crash) + VC++-Runtime-Check."""

from src import errors
from src.errors import classify_win_exit_code


def test_sac_block_wird_erkannt():
    # Real diagnostizierter Fall: whisper-server starb mit 3236495362,
    # identisch mit CodeIntegrity-Status 0xC0E90002 (Smart App Control)
    assert classify_win_exit_code(3236495362) == "err.hint.sac"
    assert classify_win_exit_code(0xC0E90002) == "err.hint.sac"


def test_signed_und_unsigned_codes_sind_gleichwertig():
    # subprocess liefert Exit-Codes je nach Pfad signed oder unsigned
    assert classify_win_exit_code(3236495362 - 2**32) == "err.hint.sac"
    assert classify_win_exit_code(-1073741515) == "err.hint.vcredist"  # 0xC0000135


def test_dll_not_found_ist_vcredist():
    assert classify_win_exit_code(0xC0000135) == "err.hint.vcredist"
    assert classify_win_exit_code(3221225781) == "err.hint.vcredist"


def test_crash_codes():
    assert classify_win_exit_code(0xC0000409) == "err.hint.crash"
    assert classify_win_exit_code(0xC0000005) == "err.hint.crash"


def test_unbekannte_codes_liefern_none():
    assert classify_win_exit_code(0) is None
    assert classify_win_exit_code(1) is None
    assert classify_win_exit_code(-1) is None


def test_check_vcredist_wirft_nie_und_findet_runtime():
    # Dev-Maschine wie CI-Runner haben die VC++-Runtime installiert;
    # wichtiger noch: der Check darf niemals eine Exception durchlassen
    assert errors.check_vcredist() is True
