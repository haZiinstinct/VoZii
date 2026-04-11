import logging
import os
import shutil

import yaml

from src.paths import BASE_DIR

log = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "hotkey": "ctrl+shift+space",
    "mode": "push_to_talk",
    "language": "de",
    "model_size": "small",
    "audio_feedback": True,
    "gpu_type": "auto",
    "audio_device": None,
    "show_overlay": True,
    "auto_start": False,
    "post_processing_mode": "off",
    "ollama_model": "llama3.2:3b",
}

CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
DEFAULT_CONFIG_PATH = os.path.join(BASE_DIR, "config.default.yaml")


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        if os.path.exists(DEFAULT_CONFIG_PATH):
            shutil.copy2(DEFAULT_CONFIG_PATH, CONFIG_PATH)
        else:
            save_config(DEFAULT_CONFIG)

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
    except Exception as e:
        log.warning("Config corrupt, using defaults: %s", e)
        user_config = {}

    config = dict(DEFAULT_CONFIG)
    config.update(user_config)

    # Migration v1.3.x -> v1.4.0: clean/format -> smart
    if config.get("post_processing_mode") in ("clean", "format"):
        log.info("Migration: post_processing_mode %s -> smart",
                 config["post_processing_mode"])
        config["post_processing_mode"] = "smart"
        save_config(config)

    return config


def save_config(config: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
