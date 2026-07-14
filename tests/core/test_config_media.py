"""Tests for ConfigManager.get_media_config, the `media:` fymo.yml section."""
from pathlib import Path

from fymo.core.config import ConfigManager


def test_returns_empty_list_when_media_section_absent(tmp_path: Path):
    cm = ConfigManager(tmp_path)
    assert cm.get_media_config() == []


def test_returns_the_media_section_when_present(tmp_path: Path):
    entries = [{"prefix": "/media/videos/", "dir": "data/videos", "extensions": ["webm"]}]
    cm = ConfigManager(tmp_path, initial_config={"media": entries})
    assert cm.get_media_config() == entries


def test_returns_empty_list_when_media_section_is_explicitly_null(tmp_path: Path):
    cm = ConfigManager(tmp_path, initial_config={"media": None})
    assert cm.get_media_config() == []
