"""Tests for build_storage_provider, mirrors fymo.jobs.providers.registry's
tests, plus the one deliberate difference: no config means no default
provider (auth/jobs/broadcasts all fall back to a builtin; storage doesn't,
since silently writing to local disk is exactly the footgun this exists to
avoid)."""
from pathlib import Path

import pytest

from fymo.storage.providers.local import LocalStorageProvider
from fymo.storage.registry import StorageConfigError, build_storage_provider


def test_absent_config_raises_no_default(tmp_path: Path):
    with pytest.raises(StorageConfigError, match="no default provider"):
        build_storage_provider(None, tmp_path)


def test_bare_string_builds_local_rooted_at_project_root(tmp_path: Path):
    provider = build_storage_provider("local", tmp_path)
    assert isinstance(provider, LocalStorageProvider)
    provider.write("foo.txt", b"hi")
    assert (tmp_path / "foo.txt").read_bytes() == b"hi"


def test_dict_config_roots_local_at_project_root_subdir(tmp_path: Path):
    provider = build_storage_provider({"provider": "local", "root": "data/x"}, tmp_path)
    assert isinstance(provider, LocalStorageProvider)
    provider.write("foo.txt", b"hi")
    assert (tmp_path / "data" / "x" / "foo.txt").read_bytes() == b"hi"


def test_unknown_builtin_string_raises(tmp_path: Path):
    with pytest.raises(StorageConfigError, match="unknown built-in storage provider: 'nope'"):
        build_storage_provider("nope", tmp_path)


def test_dotted_class_path_returns_working_custom_provider(tmp_path: Path):
    provider = build_storage_provider(
        {"class": "tests.storage.fixtures.custom_provider.EchoStorageProvider"},
        tmp_path,
    )
    from tests.storage.fixtures.custom_provider import EchoStorageProvider

    assert isinstance(provider, EchoStorageProvider)

    provider.write("key", b"payload")
    assert provider.read("key") == b"payload"


def test_invalid_config_type_raises(tmp_path: Path):
    with pytest.raises(StorageConfigError, match="must be a string or object"):
        build_storage_provider(123, tmp_path)
