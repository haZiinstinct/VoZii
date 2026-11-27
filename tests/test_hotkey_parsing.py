"""Hotkey-String-Parsing (reine Logik, keine Listener)."""

from src.config import _is_valid_hotkey
from src.hotkey import _parse_hotkey


def test_parse_simple_combo():
    assert _parse_hotkey("ctrl+shift+space") == ["ctrl", "shift", "space"]


def test_parse_normalizes_case_and_spaces():
    assert _parse_hotkey(" Ctrl + Mouse4 ") == ["ctrl", "mouse4"]


def test_parse_single_key():
    assert _parse_hotkey("f12") == ["f12"]


def test_is_valid_hotkey_accepts_common_formats():
    for s in ("ctrl+shift+space", "mouse4", "f5", "a", "ctrl+mouse5", "caps_lock"):
        assert _is_valid_hotkey(s), s


def test_is_valid_hotkey_rejects_garbage():
    for s in ("", "  ", "ctrl++space", "+", "ctrl+", None, 5, "ctrl+sp ace", "ctrl+spa#ce"):
        assert not _is_valid_hotkey(s), s


def test_ctrl_letter_control_char_matches_and_names():
    """Unter Windows liefert Ctrl+R KeyCode(vk=82, char='\\x12')."""
    from pynput.keyboard import KeyCode

    from src.hotkey import _key_matches_part, key_to_name

    ctrl_r = KeyCode(vk=82, char="\x12")
    assert key_to_name(ctrl_r) == "r"
    assert _is_valid_hotkey("ctrl+" + key_to_name(ctrl_r))
    assert _key_matches_part(ctrl_r, "r") is True
    assert _key_matches_part(ctrl_r, "k") is False

    # Shift+1 -> char='!', vk=49 -> sauber als '1' abbildbar
    shift_1 = KeyCode(vk=49, char="!")
    assert key_to_name(shift_1) == "1"
    assert _key_matches_part(shift_1, "1") is True
