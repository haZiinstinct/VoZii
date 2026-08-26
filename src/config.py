import logging
import os
import shutil

import yaml

from src.i18n import DICTATION_LANGS, UI_LANGUAGES, detect_system_language
from src.paths import BASE_DIR

log = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "hotkey": "ctrl+shift+space",
    "mode": "push_to_talk",
    "language": "auto",
    "ui_language": "",  # leer -> beim First-Run aus System-Sprache erkannt
    "model_size": "large-v3-turbo-q5_0",
    "audio_feedback": True,
    "gpu_type": "auto",
    "audio_device": None,
    "show_overlay": True,
    "auto_start": False,
    "post_processing_mode": "off",
    "ollama_model": "qwen2.5:3b",
    "performance_mode": "speed",
    "initial_prompt": "",
    "use_server": True,
    "restore_clipboard": True,
    "history_enabled": True,
    "update_check": True,
    "gpu_cache_type": None,
    "gpu_cache_name": None,
    "first_run_done": False,
}

# Erlaubte Werte je Key. None-Eintrag = Key darf None sein.
_ALLOWED_VALUES = {
    "mode": {"push_to_talk", "toggle"},
    # Diktat-Sprache: gaengige Whisper-Codes + auto (deckt alle ~99 ab)
    "language": set(DICTATION_LANGS) | {"auto"},
    # tiny/small/medium = Legacy (Bestandsnutzer), turbo = aktuelle Stufen
    "model_size": {"tiny", "small", "medium", "large-v3-turbo-q5_0", "large-v3-turbo"},
    "gpu_type": {"auto", "nvidia", "amd", "cpu"},
    "post_processing_mode": {"off", "smart", "prompt"},
    "performance_mode": {"speed", "quality"},
}

_BOOL_KEYS = {
    "audio_feedback", "show_overlay", "auto_start", "use_server",
    "restore_clipboard", "history_enabled", "first_run_done", "update_check",
}

CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
DEFAULT_CONFIG_PATH = os.path.join(BASE_DIR, "config.default.yaml")


def _is_valid_hotkey(hotkey_str) -> bool:
    """Strukturelle Pruefung ohne pynput-Import: 'ctrl+shift+space', 'mouse4', 'f5'."""
    if not isinstance(hotkey_str, str) or not hotkey_str.strip():
        return False
    parts = [p.strip() for p in hotkey_str.split("+")]
    return all(p and all(c.isalnum() or c == "_" for c in p) for p in parts)


def _validate(config: dict) -> dict:
    """Ersetzt ungueltige Werte durch Defaults (manuell editierte config.yaml)."""
    for key, allowed in _ALLOWED_VALUES.items():
        if config.get(key) not in allowed:
            log.warning("Config: %s=%r ungueltig, nutze %r",
                        key, config.get(key), DEFAULT_CONFIG[key])
            config[key] = DEFAULT_CONFIG[key]

    for key in _BOOL_KEYS:
        if not isinstance(config.get(key), bool):
            config[key] = DEFAULT_CONFIG[key]

    if not _is_valid_hotkey(config.get("hotkey")):
        log.warning("Config: hotkey=%r ungueltig, nutze %r",
                    config.get("hotkey"), DEFAULT_CONFIG["hotkey"])
        config["hotkey"] = DEFAULT_CONFIG["hotkey"]

    if config.get("audio_device") is not None and not isinstance(config["audio_device"], str):
        config["audio_device"] = None

    if not isinstance(config.get("ollama_model"), str) or not config["ollama_model"].strip():
        config["ollama_model"] = DEFAULT_CONFIG["ollama_model"]

    # Eigene Begriffe (Whisper initial_prompt): Whisper sieht nur ~224 Tokens
    # Prompt-Fenster — laengere Eingaben bringen nichts und werden gekappt
    if not isinstance(config.get("initial_prompt"), str):
        config["initial_prompt"] = ""
    config["initial_prompt"] = config["initial_prompt"].strip()[:600]

    # Oberflaechen-Sprache: leer/ungueltig -> aus der System-Sprache ableiten
    if config.get("ui_language") not in UI_LANGUAGES:
        config["ui_language"] = detect_system_language()

    return config


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        if os.path.exists(DEFAULT_CONFIG_PATH):
            shutil.copy2(DEFAULT_CONFIG_PATH, CONFIG_PATH)
        else:
            save_config(DEFAULT_CONFIG)

    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
    except Exception as e:
        log.warning("Config corrupt, using defaults: %s", e)
        user_config = {}

    # yaml.safe_load kann auch Listen/Strings/Zahlen liefern
    if not isinstance(user_config, dict):
        log.warning("Config ist kein Mapping (%s), nutze Defaults", type(user_config).__name__)
        user_config = {}

    config = dict(DEFAULT_CONFIG)
    config.update(user_config)

    # Migration v1.3.x -> v1.4.0: clean/format -> smart
    if config.get("post_processing_mode") in ("clean", "format"):
        log.info("Migration: post_processing_mode %s -> smart",
                 config["post_processing_mode"])
        config["post_processing_mode"] = "smart"
        save_config(config)

    return _validate(config)


def save_config(config: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
