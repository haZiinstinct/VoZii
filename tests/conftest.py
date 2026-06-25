"""Test-Fixtures — leiten alle Pfade auf tmp_path um.

Kein Test darf ins echte BASE_DIR (%LOCALAPPDATA% bzw. Projekt-Root)
schreiben. Audio/Netzwerk wird in den jeweiligen Tests gemockt.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def reset_ui_language():
    """i18n haelt die aktive Sprache global — vor jedem Test auf 'de' zuruecksetzen,
    damit ein set_language() in einem Test die String-Erwartungen anderer nicht stoert."""
    from src import i18n

    i18n.set_language("de")
    yield
    i18n.set_language("de")


@pytest.fixture
def config_paths(tmp_path, monkeypatch):
    """config.py liest/schreibt nur unter tmp_path."""
    from src import config as config_mod

    config_path = tmp_path / "config.yaml"
    default_path = tmp_path / "config.default.yaml"
    monkeypatch.setattr(config_mod, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", str(default_path))
    return config_path, default_path
