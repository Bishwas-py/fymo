"""Tests for ConfigManager.get_jobs_config — the `jobs:` fymo.yml section."""
from pathlib import Path

from fymo.core.config import ConfigManager


def test_returns_empty_dict_when_jobs_section_absent(tmp_path: Path):
    cm = ConfigManager(tmp_path)
    assert cm.get_jobs_config() == {}


def test_returns_the_jobs_section_when_present(tmp_path: Path):
    cm = ConfigManager(tmp_path, initial_config={"jobs": {"provider": "procrastinate"}})
    assert cm.get_jobs_config() == {"provider": "procrastinate"}


def test_returns_empty_dict_when_jobs_section_is_explicitly_null(tmp_path: Path):
    cm = ConfigManager(tmp_path, initial_config={"jobs": None})
    assert cm.get_jobs_config() == {}


def test_broadcasts_config_returns_empty_dict_when_absent(tmp_path: Path):
    cm = ConfigManager(tmp_path)
    assert cm.get_broadcasts_config() == {}


def test_broadcasts_config_returns_the_section_when_present(tmp_path: Path):
    cm = ConfigManager(tmp_path, initial_config={"broadcasts": {"provider": "postgres"}})
    assert cm.get_broadcasts_config() == {"provider": "postgres"}
