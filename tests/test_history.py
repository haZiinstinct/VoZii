"""Transkriptions-Historie: Limit, Reihenfolge, Atomik, korrupte Dateien."""

import json

from src.history import TranscriptionHistory


def _history(tmp_path, limit=50):
    return TranscriptionHistory(path=str(tmp_path / "history.json"), limit=limit)


def test_add_and_get_recent_newest_first(tmp_path):
    h = _history(tmp_path)
    for i in range(7):
        h.add(f"eintrag {i}")
    recent = h.get_recent(5)
    assert [e["text"] for e in recent] == [
        "eintrag 6", "eintrag 5", "eintrag 4", "eintrag 3", "eintrag 2"]
    assert all("ts" in e for e in recent)


def test_limit_is_enforced(tmp_path):
    h = _history(tmp_path, limit=10)
    for i in range(25):
        h.add(f"e{i}")
    assert h.count() == 10
    assert h.get_recent(1)[0]["text"] == "e24"


def test_persists_across_instances(tmp_path):
    _history(tmp_path).add("bleibt erhalten")
    h2 = _history(tmp_path)
    assert h2.count() == 1
    assert h2.get_recent(1)[0]["text"] == "bleibt erhalten"


def test_corrupt_file_starts_empty(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("{kaputt", encoding="utf-8")
    h = TranscriptionHistory(path=str(path))
    assert h.count() == 0
    h.add("neu")  # und ist wieder schreibbar
    assert h.count() == 1


def test_wrong_shape_entries_are_dropped(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(json.dumps(["string", {"text": 42}, {"text": "ok", "ts": "x"}]),
                    encoding="utf-8")
    h = TranscriptionHistory(path=str(path))
    assert h.count() == 1
    assert h.get_recent(1)[0]["text"] == "ok"


def test_clear(tmp_path):
    h = _history(tmp_path)
    h.add("weg damit")
    h.clear()
    assert h.count() == 0
    assert _history(tmp_path).count() == 0  # auch auf Disk


def test_unicode_and_multiline(tmp_path):
    text = "Zeile eins\nZeile zwei — äöü 😀"
    h = _history(tmp_path)
    h.add(text)
    assert _history(tmp_path).get_recent(1)[0]["text"] == text


def test_empty_text_is_ignored(tmp_path):
    h = _history(tmp_path)
    h.add("")
    assert h.count() == 0


def test_no_tmp_file_left_behind(tmp_path):
    h = _history(tmp_path)
    h.add("x")
    assert not (tmp_path / "history.json.tmp").exists()
