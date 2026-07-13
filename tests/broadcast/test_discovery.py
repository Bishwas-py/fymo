"""Tests for fymo.broadcast.discovery — app/broadcasts/*.py channel files."""
from pathlib import Path

import pytest

from fymo.broadcast.discovery import DuplicateChannelError, discover_broadcast_channels


def _write_app(tmp_path: Path, module: str, source: str) -> Path:
    bdir = tmp_path / "app" / "broadcasts"
    bdir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "app" / "__init__.py").touch()
    (bdir / "__init__.py").touch()
    (bdir / f"{module}.py").write_text(source)
    return tmp_path


def test_returns_empty_dict_when_no_broadcasts_dir(tmp_path: Path):
    assert discover_broadcast_channels(tmp_path) == {}


def test_discovers_channels_keyed_by_name_with_module(tmp_path: Path):
    _write_app(tmp_path, "runs", "def run_status(run_id: str) -> dict:\n    ...\n")
    channels = discover_broadcast_channels(tmp_path)
    assert set(channels) == {"run_status"}
    module, fn = channels["run_status"]
    assert module == "runs"
    assert fn.__name__ == "run_status"


def test_skips_private_functions_and_modules(tmp_path: Path):
    _write_app(tmp_path, "runs", "def _helper():\n    ...\n\ndef visible(x: str) -> dict:\n    ...\n")
    _write_app(tmp_path, "_private", "def hidden(x: str) -> dict:\n    ...\n")
    channels = discover_broadcast_channels(tmp_path)
    assert set(channels) == {"visible"}


def test_duplicate_channel_names_across_modules_raise(tmp_path: Path):
    _write_app(tmp_path, "runs", "def status(id: str) -> dict:\n    ...\n")
    _write_app(tmp_path, "flows", "def status(id: str) -> dict:\n    ...\n")
    with pytest.raises(DuplicateChannelError, match="status"):
        discover_broadcast_channels(tmp_path)
