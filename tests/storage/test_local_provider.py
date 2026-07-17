"""Tests for LocalStorageProvider (fymo/storage/providers/local.py).

Mirrors tests/core/test_expose.py's traversal/symlink coverage, since
LocalStorageProvider carries over that module's containment check.
"""
from pathlib import Path

import pytest

from fymo.storage.base import RangeNotSatisfiable
from fymo.storage.providers.local import LocalStorageProvider


def test_write_then_read_round_trip(tmp_path: Path):
    provider = LocalStorageProvider(project_root=tmp_path)
    provider.write("videos/foo.webm", b"hello world")
    assert provider.read("videos/foo.webm") == b"hello world"


def test_read_with_valid_range_returns_slice(tmp_path: Path):
    provider = LocalStorageProvider(project_root=tmp_path)
    provider.write("clip.webm", b"0123456789")
    assert provider.read("clip.webm", range=(2, 5)) == b"2345"


def test_read_with_out_of_bounds_range_raises_range_not_satisfiable(tmp_path: Path):
    provider = LocalStorageProvider(project_root=tmp_path)
    provider.write("clip.webm", b"0123456789")
    with pytest.raises(RangeNotSatisfiable) as exc_info:
        provider.read("clip.webm", range=(20, 30))
    assert exc_info.value.size == 10


def test_read_range_end_past_eof_is_clamped_not_rejected(tmp_path: Path):
    provider = LocalStorageProvider(project_root=tmp_path)
    provider.write("clip.webm", b"0123456789")
    assert provider.read("clip.webm", range=(5, 999)) == b"56789"


def test_size_matches_written_byte_count(tmp_path: Path):
    provider = LocalStorageProvider(project_root=tmp_path)
    provider.write("clip.webm", b"0123456789")
    assert provider.size("clip.webm") == 10


def test_exists_true_then_false_after_delete(tmp_path: Path):
    provider = LocalStorageProvider(project_root=tmp_path)
    provider.write("clip.webm", b"data")
    assert provider.exists("clip.webm") is True
    provider.delete("clip.webm")
    assert provider.exists("clip.webm") is False


def test_exists_false_for_missing_key(tmp_path: Path):
    provider = LocalStorageProvider(project_root=tmp_path)
    assert provider.exists("nope.webm") is False


def test_url_for_always_returns_none(tmp_path: Path):
    provider = LocalStorageProvider(project_root=tmp_path)
    provider.write("clip.webm", b"data")
    assert provider.url_for("clip.webm") is None


def test_read_missing_key_raises_file_not_found(tmp_path: Path):
    provider = LocalStorageProvider(project_root=tmp_path)
    with pytest.raises(FileNotFoundError):
        provider.read("nope.webm")


def test_size_missing_key_raises_file_not_found(tmp_path: Path):
    provider = LocalStorageProvider(project_root=tmp_path)
    with pytest.raises(FileNotFoundError):
        provider.size("nope.webm")


def test_delete_missing_key_raises_file_not_found(tmp_path: Path):
    provider = LocalStorageProvider(project_root=tmp_path)
    with pytest.raises(FileNotFoundError):
        provider.delete("nope.webm")


@pytest.mark.parametrize("method", ["read", "size", "delete", "exists"])
def test_traversal_key_raises_value_error(tmp_path: Path, method: str):
    provider = LocalStorageProvider(project_root=tmp_path)
    with pytest.raises(ValueError):
        getattr(provider, method)("../escape")


def test_traversal_key_raises_value_error_on_write(tmp_path: Path):
    provider = LocalStorageProvider(project_root=tmp_path)
    with pytest.raises(ValueError):
        provider.write("../escape", b"data")


def test_symlink_inside_root_pointing_outside_is_rejected(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    secret = tmp_path / "secret.webm"
    secret.write_bytes(b"top secret, outside root")
    (root / "evil.webm").symlink_to(secret)

    provider = LocalStorageProvider(project_root=root)
    with pytest.raises(ValueError):
        provider.read("evil.webm")


def test_no_root_resolves_against_project_root(tmp_path: Path):
    provider = LocalStorageProvider(project_root=tmp_path)
    provider.write("foo.txt", b"hi")
    assert (tmp_path / "foo.txt").read_bytes() == b"hi"


def test_root_subdir_resolves_relative_to_project_root(tmp_path: Path):
    provider = LocalStorageProvider(root="data/x", project_root=tmp_path)
    provider.write("foo.txt", b"hi")
    assert (tmp_path / "data" / "x" / "foo.txt").read_bytes() == b"hi"
