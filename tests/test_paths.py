"""BASE_DIR-Aufloesung: Bestandsnutzer neben der Exe vs. %LOCALAPPDATA%."""

from src import paths


def test_fresh_install_uses_appdata(tmp_path, monkeypatch):
    exe_dir = tmp_path / "exe"
    appdata = tmp_path / "appdata"
    exe_dir.mkdir()
    monkeypatch.setattr(paths, "_exe_dir", lambda: str(exe_dir))
    monkeypatch.setattr(paths, "_appdata_dir", lambda: str(appdata))
    assert paths.get_base_dir() == str(appdata)


def test_existing_config_next_to_exe_is_kept(tmp_path, monkeypatch):
    exe_dir = tmp_path / "exe"
    exe_dir.mkdir()
    (exe_dir / "config.yaml").write_text("hotkey: f5\n", encoding="utf-8")
    monkeypatch.setattr(paths, "_exe_dir", lambda: str(exe_dir))
    monkeypatch.setattr(paths, "_appdata_dir", lambda: str(tmp_path / "appdata"))
    assert paths.get_base_dir() == str(exe_dir)


def test_existing_whisper_dir_next_to_exe_is_kept(tmp_path, monkeypatch):
    exe_dir = tmp_path / "exe"
    (exe_dir / "whisper-cpp").mkdir(parents=True)
    monkeypatch.setattr(paths, "_exe_dir", lambda: str(exe_dir))
    monkeypatch.setattr(paths, "_appdata_dir", lambda: str(tmp_path / "appdata"))
    assert paths.get_base_dir() == str(exe_dir)


def test_existing_data_but_readonly_falls_back(tmp_path, monkeypatch):
    exe_dir = tmp_path / "exe"
    exe_dir.mkdir()
    (exe_dir / "config.yaml").write_text("", encoding="utf-8")
    appdata = tmp_path / "appdata"
    monkeypatch.setattr(paths, "_exe_dir", lambda: str(exe_dir))
    monkeypatch.setattr(paths, "_appdata_dir", lambda: str(appdata))
    monkeypatch.setattr(paths, "_is_writable", lambda _: False)
    assert paths.get_base_dir() == str(appdata)


def test_kaputtes_appdata_faellt_auf_temp_zurueck(tmp_path, monkeypatch):
    # get_base_dir laeuft auf Import-Ebene — es darf NIE eine Exception
    # durchlassen (frueher: stummer Tod der --windowed-Exe)
    import tempfile

    def broken_appdata():
        raise OSError("LOCALAPPDATA gesperrt")

    monkeypatch.setattr(paths, "BASE_DIR_FALLBACK", None)
    monkeypatch.setattr(paths, "_exe_dir", lambda: str(tmp_path / "exe"))
    monkeypatch.setattr(paths, "_appdata_dir", broken_appdata)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "t"))

    result = paths.get_base_dir()
    assert result == str(tmp_path / "t" / "VoZii")
    assert paths.BASE_DIR_FALLBACK is not None
    monkeypatch.setattr(paths, "BASE_DIR_FALLBACK", None)
