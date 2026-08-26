"""Single-Instance-Lock: ok / busy / error (tri-state)."""

from src import logger


def _use_lock(monkeypatch, path):
    monkeypatch.setattr(logger, "LOCK_PATH", str(path))
    monkeypatch.setattr(logger, "_lock_file", None)


def test_erste_instanz_bekommt_ok(tmp_path, monkeypatch):
    _use_lock(monkeypatch, tmp_path / "vozii.lock")
    assert logger.acquire_single_instance() == "ok"
    logger._lock_file.close()


def test_zweite_instanz_ist_busy(tmp_path, monkeypatch):
    _use_lock(monkeypatch, tmp_path / "vozii.lock")
    assert logger.acquire_single_instance() == "ok"
    first = logger._lock_file

    logger._lock_file = None
    assert logger.acquire_single_instance() == "busy"
    first.close()


def test_lockdatei_nicht_anlegbar_ist_error_nicht_busy(tmp_path, monkeypatch):
    # Frueher wurde das faelschlich als "VoZii laeuft bereits" gemeldet
    _use_lock(monkeypatch, tmp_path / "gibtsnicht" / "vozii.lock")
    assert logger.acquire_single_instance() == "error"
