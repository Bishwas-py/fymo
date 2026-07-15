"""Tests for the process-wide StorageProvider singleton and its config-driven
init helper (issue #31) — mirrors fymo.jobs's get_job_provider()/
init_job_provider() tests (tests/jobs/test_provider_singleton.py), with the
one deliberate difference: storage has no default provider, so
get_storage_provider() raises instead of silently constructing one when
nothing has called init_storage_provider() yet."""
from pathlib import Path

import pytest

from fymo.storage import (
    get_storage_provider,
    init_storage_provider,
    reset_storage_provider,
    set_storage_provider,
)
from fymo.storage.providers.local import LocalStorageProvider
from fymo.storage.registry import StorageConfigError


@pytest.fixture(autouse=True)
def _reset():
    reset_storage_provider()
    yield
    reset_storage_provider()


def test_get_storage_provider_raises_before_init():
    with pytest.raises(RuntimeError, match="storage is not initialized"):
        get_storage_provider()


def test_init_storage_provider_builds_and_registers_singleton(tmp_path: Path):
    provider = init_storage_provider(tmp_path, {"provider": "local"})

    assert isinstance(provider, LocalStorageProvider)
    assert get_storage_provider() is provider


def test_get_storage_provider_is_a_process_wide_singleton(tmp_path: Path):
    init_storage_provider(tmp_path, {"provider": "local"})
    assert get_storage_provider() is get_storage_provider()


def test_set_storage_provider_overrides(tmp_path: Path):
    init_storage_provider(tmp_path, {"provider": "local"})
    custom = LocalStorageProvider(project_root=tmp_path, root="elsewhere")
    set_storage_provider(custom)
    assert get_storage_provider() is custom


def test_init_storage_provider_with_no_config_raises_no_default(tmp_path: Path):
    with pytest.raises(StorageConfigError, match="no default provider"):
        init_storage_provider(tmp_path, None)
    with pytest.raises(RuntimeError, match="storage is not initialized"):
        get_storage_provider()


def test_reset_storage_provider_clears_the_singleton(tmp_path: Path):
    init_storage_provider(tmp_path, {"provider": "local"})
    reset_storage_provider()
    with pytest.raises(RuntimeError, match="storage is not initialized"):
        get_storage_provider()
