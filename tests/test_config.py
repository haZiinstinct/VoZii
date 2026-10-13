"""Config-Laden: korrupte YAML, ungueltige Werte, Migration."""

import yaml

from src.config import DEFAULT_CONFIG, load_config


def _write(path, content: str):
    path.write_text(content, encoding="utf-8")


def test_missing_file_creates_defaults(config_paths):
    config_path, _ = config_paths
    config = load_config()
    assert config["hotkey"] == DEFAULT_CONFIG["hotkey"]
    assert config_path.exists()


def test_non_dict_yaml_list(config_paths):
    config_path, _ = config_paths
    _write(config_path, "- eins\n- zwei\n")
    config = load_config()
    assert config["model_size"] == DEFAULT_CONFIG["model_size"]


def test_non_dict_yaml_scalar(config_paths):
    config_path, _ = config_paths
    _write(config_path, "42\n")
    assert load_config()["hotkey"] == DEFAULT_CONFIG["hotkey"]


def test_broken_yaml_syntax(config_paths):
    config_path, _ = config_paths
    _write(config_path, "hotkey: [unclosed\n  nope::\n\t")
    assert load_config()["hotkey"] == DEFAULT_CONFIG["hotkey"]


def test_invalid_enum_values_fall_back(config_paths):
    config_path, _ = config_paths
    _write(config_path, yaml.dump({
        "model_size": "gigantic",
        "mode": "hold",
        "language": "klingon",
        "post_processing_mode": "clean2",
        "performance_mode": "ludicrous",
    }))
    config = load_config()
    assert config["model_size"] == "large-v3-turbo-q5_0"
    assert config["mode"] == "push_to_talk"
    assert config["language"] == "auto"  # Default ist jetzt 'auto' (universeller)
    assert config["post_processing_mode"] == "off"
    assert config["performance_mode"] == "speed"


def test_invalid_hotkey_falls_back(config_paths):
    config_path, _ = config_paths
    for bad in ("", "   ", "ctrl++space", None, 123, "ctrl+sp ace"):
        _write(config_path, yaml.dump({"hotkey": bad}))
        assert load_config()["hotkey"] == DEFAULT_CONFIG["hotkey"], bad


def test_valid_hotkeys_kept(config_paths):
    config_path, _ = config_paths
    for good in ("ctrl+shift+space", "mouse4", "f5", "ctrl+mouse5", "a"):
        _write(config_path, yaml.dump({"hotkey": good}))
        assert load_config()["hotkey"] == good


def test_bool_keys_validated(config_paths):
    config_path, _ = config_paths
    _write(config_path, yaml.dump({"use_server": "ja", "history_enabled": 1}))
    config = load_config()
    assert config["use_server"] is True
    assert config["history_enabled"] is True


def test_migration_clean_format_to_smart(config_paths):
    config_path, _ = config_paths
    _write(config_path, yaml.dump({"post_processing_mode": "clean"}))
    assert load_config()["post_processing_mode"] == "smart"
    # Migration wurde persistiert
    persisted = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert persisted["post_processing_mode"] == "smart"


def test_missing_keys_get_defaults(config_paths):
    config_path, _ = config_paths
    _write(config_path, yaml.dump({"language": "en"}))
    config = load_config()
    assert config["language"] == "en"
    for key in DEFAULT_CONFIG:
        assert key in config


def test_initial_prompt_default_und_kappung(config_paths):
    from src.config import load_config, save_config

    cfg = load_config()
    assert cfg["initial_prompt"] == ""

    cfg["initial_prompt"] = "  haZii, VoZii  "
    save_config(cfg)
    assert load_config()["initial_prompt"] == "haZii, VoZii"

    cfg["initial_prompt"] = "x" * 1000
    save_config(cfg)
    assert len(load_config()["initial_prompt"]) == 600

    cfg["initial_prompt"] = 42  # kein String -> Default
    save_config(cfg)
    assert load_config()["initial_prompt"] == ""


def test_save_config_atomar_bei_abbruch(config_paths, monkeypatch):
    """Exception mitten im Dump: alte Datei bleibt, keine .tmp-Leiche."""
    import pytest

    from src import config as config_mod

    config_path, _ = config_paths
    cfg = load_config()
    cfg["hotkey"] = "f8"
    config_mod.save_config(cfg)
    before = config_path.read_text(encoding="utf-8")

    def boom(*a, **kw):
        raise RuntimeError("Absturz im Dump")
    monkeypatch.setattr(config_mod.yaml, "dump", boom)
    with pytest.raises(RuntimeError):
        config_mod.save_config({"hotkey": "f9"})

    assert config_path.read_text(encoding="utf-8") == before
    assert not (config_path.parent / "config.yaml.tmp").exists()


def test_update_config_aendert_nur_genannte_keys(config_paths):
    from src.config import save_config, update_config

    cfg = load_config()
    cfg["hotkey"] = "f8"
    save_config(cfg)
    update_config(gpu_cache_type="amd", gpu_cache_name="RX 6750 XT")

    cfg = load_config()
    assert cfg["hotkey"] == "f8"
    assert (cfg["gpu_cache_type"], cfg["gpu_cache_name"]) == ("amd", "RX 6750 XT")
