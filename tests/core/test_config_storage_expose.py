"""Tests for storage.expose config access (ConfigManager.get_storage_expose_config)
and the hard removal error for the retired top-level `media:` key."""
from pathlib import Path

import pytest

from fymo.core.config import ConfigManager
from fymo.core.exceptions import ConfigurationError

_ENTRIES = [{"prefix": "/media/videos/", "dir": "videos", "extensions": ["webm"]}]


def test_returns_empty_list_when_storage_section_absent(tmp_path: Path):
    cm = ConfigManager(tmp_path)
    assert cm.get_storage_expose_config() == []


def test_returns_the_expose_entries_when_present(tmp_path: Path):
    cm = ConfigManager(tmp_path, initial_config={
        "storage": {"provider": "local", "expose": _ENTRIES},
    })
    assert cm.get_storage_expose_config() == _ENTRIES


def test_returns_empty_list_when_expose_absent_or_null(tmp_path: Path):
    assert ConfigManager(tmp_path, initial_config={
        "storage": {"provider": "local"},
    }).get_storage_expose_config() == []
    assert ConfigManager(tmp_path, initial_config={
        "storage": {"provider": "local", "expose": None},
    }).get_storage_expose_config() == []


def test_returns_empty_list_when_storage_is_a_bare_string(tmp_path: Path):
    """`storage: local` (bare-string provider selection) has no room for
    expose entries; the accessor must not crash on it."""
    cm = ConfigManager(tmp_path, initial_config={"storage": "local"})
    assert cm.get_storage_expose_config() == []


def test_top_level_media_key_raises_configuration_error(tmp_path: Path):
    """Hard break, no shim: a config still carrying the removed `media:` key
    must refuse to load, and the error is the migration doc."""
    with pytest.raises(ConfigurationError, match=r"storage\.expose") as exc:
        ConfigManager(tmp_path, initial_config={"media": _ENTRIES})
    assert "prefix/dir/extensions" in str(exc.value)


def test_top_level_media_key_in_fymo_yml_raises_configuration_error(tmp_path: Path):
    (tmp_path / "fymo.yml").write_text(
        "media:\n"
        "  - prefix: /media/videos/\n"
        "    dir: videos\n"
        "    extensions: [webm]\n"
    )
    with pytest.raises(ConfigurationError, match=r"storage\.expose"):
        ConfigManager(tmp_path)


def test_even_an_empty_media_key_raises(tmp_path: Path):
    """`media: []` is still the removed key; silently ignoring it would hide
    the migration from anyone who empties the list instead of moving it."""
    (tmp_path / "fymo.yml").write_text("media: []\n")
    with pytest.raises(ConfigurationError, match=r"storage\.expose"):
        ConfigManager(tmp_path)
