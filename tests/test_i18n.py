"""i18n: Vollstaendigkeit aller Sprachen, Platzhalter-Konsistenz, Fallback-Kette."""

import string

import pytest

from src.i18n import (
    DICTATION_LANGS,
    RTL_LANGS,
    STRINGS,
    UI_LANGUAGES,
    detect_system_language,
    get_language,
    is_rtl,
    set_language,
    t,
)


def _placeholders(s: str) -> set:
    """Benannte {platzhalter} in einem .format-String."""
    return {name for _, name, _, _ in string.Formatter().parse(s) if name}


def test_every_ui_language_has_a_string_table():
    for code in UI_LANGUAGES:
        assert code in STRINGS, f"STRINGS fehlt fuer UI-Sprache {code!r}"


def test_all_languages_have_the_same_keys():
    base = set(STRINGS["de"])
    assert base, "Basis-Sprache de darf nicht leer sein"
    for code, table in STRINGS.items():
        keys = set(table)
        missing = base - keys
        extra = keys - base
        assert not missing, f"{code}: fehlende Keys {sorted(missing)}"
        assert not extra, f"{code}: ueberzaehlige Keys {sorted(extra)}"


def test_placeholders_consistent_across_languages():
    """Jeder Key muss in jeder Sprache exakt dieselben {platzhalter} haben —
    sonst KeyError oder fehlende Werte zur Laufzeit."""
    for key, ref_text in STRINGS["de"].items():
        ref = _placeholders(ref_text)
        for code, table in STRINGS.items():
            got = _placeholders(table[key])
            assert got == ref, (
                f"{code}/{key}: Platzhalter {got} != de {ref}"
            )


def test_no_empty_translations():
    for code, table in STRINGS.items():
        for key, value in table.items():
            assert value.strip(), f"{code}/{key} ist leer"


def test_t_returns_active_language():
    set_language("en")
    assert t("btn.start") == "Start"
    set_language("de")
    assert t("btn.start") == "Starten"


def test_t_formats_kwargs():
    set_language("en")
    assert t("tray.hotkey", hotkey="CTRL+SPACE") == "Hotkey: CTRL+SPACE"
    assert "550" not in t("download.model", model="turbo")  # nur Platzhalter ersetzt
    assert t("download.model", model="turbo") == "Downloading model 'turbo'..."


def test_t_fallback_to_en_then_de(monkeypatch):
    """Fehlt ein Key in der aktiven Sprache, greift en, dann de, dann der Key."""
    # Kuenstlichen Key nur in en + de einsetzen
    monkeypatch.setitem(STRINGS["en"], "x.only_en_de", "english")
    monkeypatch.setitem(STRINGS["de"], "x.only_en_de", "deutsch")
    set_language("fr")  # hat den Key nicht
    assert t("x.only_en_de") == "english"  # Fallback en vor de


def test_t_unknown_key_returns_key_itself():
    set_language("de")
    assert t("does.not.exist") == "does.not.exist"


def test_set_language_unknown_falls_back_to_de():
    set_language("klingon")
    assert get_language() == "de"


def test_is_rtl_only_for_arabic():
    set_language("ar")
    assert is_rtl() is True
    for code in UI_LANGUAGES:
        if code == "ar":
            continue
        set_language(code)
        assert is_rtl() is False, code
    assert RTL_LANGS == {"ar"}


def test_dictation_langs_are_autonyms():
    # Diktat-Sprachen werden als Eigenname angezeigt, unabhaengig von der UI-Sprache
    assert DICTATION_LANGS["de"] == "Deutsch"
    assert DICTATION_LANGS["zh"] == "中文"
    assert DICTATION_LANGS["ja"] == "日本語"
    assert "auto" not in DICTATION_LANGS  # 'auto' ist separat (lang.auto, uebersetzt)


@pytest.mark.parametrize("lcid_primary,expected", [
    (0x07, "de"), (0x09, "en"), (0x0A, "es"), (0x0C, "fr"),
    (0x16, "pt"), (0x19, "ru"), (0x04, "zh"), (0x11, "ja"), (0x01, "ar"),
    (0x3F, "en"),  # unbekannt -> Fallback en (weltweiter Default)
])
def test_detect_system_language(monkeypatch, lcid_primary, expected):
    class FakeKernel:
        @staticmethod
        def GetUserDefaultUILanguage():
            return lcid_primary  # primaere ID liegt in den unteren 10 Bit

    class FakeWindll:
        kernel32 = FakeKernel()

    import ctypes
    monkeypatch.setattr(ctypes, "windll", FakeWindll(), raising=False)
    assert detect_system_language() == expected
