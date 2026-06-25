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
