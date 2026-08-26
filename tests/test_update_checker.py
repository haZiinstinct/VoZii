"""Update-Checker: Versionsvergleich, stille Fehler, Callback-Verhalten."""

import io
import json
import threading
import urllib.error

from src import update_checker


def test_is_newer():
    assert update_checker.is_newer("1.8.0", "1.7.1") is True
    assert update_checker.is_newer("1.10.0", "1.9.9") is True   # kein String-Vergleich
    assert update_checker.is_newer("2.0.0", "1.99.99") is True
    assert update_checker.is_newer("1.7.1", "1.7.1") is False
    assert update_checker.is_newer("1.7.0", "1.7.1") is False
    assert update_checker.is_newer("v1.8.0", "1.7.1") is True   # v-Prefix tolerieren


def test_is_newer_mit_muell_ist_nie_true():
    assert update_checker.is_newer("beta", "1.7.1") is False
    assert update_checker.is_newer("", "1.7.1") is False
    assert update_checker.is_newer("1.8.0", "kaputt") is False


class _Resp:
    def __init__(self, payload: bytes):
        self._buf = io.BytesIO(payload)

    def read(self):
        return self._buf.read()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_latest_version_ok(monkeypatch):
    payload = json.dumps({"tag_name": "v1.9.0"}).encode()
    monkeypatch.setattr(update_checker.urllib.request, "urlopen",
                        lambda req, timeout: _Resp(payload))
    assert update_checker.fetch_latest_version() == "1.9.0"


def test_fetch_latest_version_fehler_bleiben_still(monkeypatch):
    def raise_(req, timeout):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(update_checker.urllib.request, "urlopen", raise_)
    assert update_checker.fetch_latest_version() is None

    monkeypatch.setattr(update_checker.urllib.request, "urlopen",
                        lambda req, timeout: _Resp(b"kein json"))
    assert update_checker.fetch_latest_version() is None

    monkeypatch.setattr(update_checker.urllib.request, "urlopen",
                        lambda req, timeout: _Resp(b"{}"))
    assert update_checker.fetch_latest_version() is None


def _run_check(monkeypatch, latest: str, current: str) -> list:
    calls = []
    done = threading.Event()
    monkeypatch.setattr(update_checker, "fetch_latest_version", lambda timeout=4.0: latest)

    def on_update(v):
        calls.append(v)

    update_checker.check_async(current, on_update)
    # check_async ist fire-and-forget — kurz auf den Daemon-Thread warten
    for th in threading.enumerate():
        if th.name == "update-check":
            th.join(timeout=5)
    done.set()
    return calls


def test_check_async_meldet_nur_neuere_version(monkeypatch):
    assert _run_check(monkeypatch, "1.9.0", "1.8.0") == ["1.9.0"]
    assert _run_check(monkeypatch, "1.8.0", "1.8.0") == []
    assert _run_check(monkeypatch, None, "1.8.0") == []
