"""The `auth:` config block was removed with the framework-owned auth
model (issue #80 phase 6): identity now lives in code (app/auth/), and a
fymo.yml still carrying the block must fail loudly with the migration
text at both surfaces, boot (ConfigManager) and build hygiene (`fymo
build` / `fymo dev`), mirroring the `media:` removal.
"""
from pathlib import Path

import pytest

from fymo.build.hygiene import check_auth_key_removed
from fymo.core.config import AUTH_KEY_REMOVED_ERROR, ConfigManager
from fymo.core.exceptions import ConfigurationError


def _write_fymo_yml(tmp_path: Path, body: str) -> Path:
    (tmp_path / "fymo.yml").write_text("name: t\nroutes: {}\n" + body)
    return tmp_path


# --------------- the message is the migration doc ---------------


def test_error_text_carries_the_exact_fix():
    assert "auth:" in AUTH_KEY_REMOVED_ERROR
    assert "fymo generate auth" in AUTH_KEY_REMOVED_ERROR
    assert "--clerk" in AUTH_KEY_REMOVED_ERROR
    assert "--skeleton" in AUTH_KEY_REMOVED_ERROR
    assert "@require_auth" in AUTH_KEY_REMOVED_ERROR
    assert "require_auth" in AUTH_KEY_REMOVED_ERROR


# --------------- boot surface: ConfigManager ---------------


def test_boot_refuses_auth_block(tmp_path: Path):
    _write_fymo_yml(tmp_path, "auth:\n  enabled: true\n")
    with pytest.raises(ConfigurationError) as excinfo:
        ConfigManager(tmp_path)
    assert str(excinfo.value) == AUTH_KEY_REMOVED_ERROR


def test_boot_refuses_auth_block_even_when_disabled(tmp_path: Path):
    """Key presence is the violation, not its value: `enabled: false` is
    still the removed vocabulary and must name the fix."""
    _write_fymo_yml(tmp_path, "auth:\n  enabled: false\n")
    with pytest.raises(ConfigurationError, match="fymo generate auth"):
        ConfigManager(tmp_path)


def test_boot_refuses_empty_auth_block(tmp_path: Path):
    _write_fymo_yml(tmp_path, "auth:\n")
    with pytest.raises(ConfigurationError, match="fymo generate auth"):
        ConfigManager(tmp_path)


def test_boot_without_auth_block_is_fine(tmp_path: Path):
    _write_fymo_yml(tmp_path, "")
    ConfigManager(tmp_path)


# --------------- build surface: hygiene check ---------------


def test_build_check_flags_auth_block(tmp_path: Path):
    _write_fymo_yml(tmp_path, "auth:\n  enabled: true\n")
    assert check_auth_key_removed(tmp_path) == [AUTH_KEY_REMOVED_ERROR]


def test_build_check_flags_empty_auth_block(tmp_path: Path):
    _write_fymo_yml(tmp_path, "auth:\n")
    assert check_auth_key_removed(tmp_path) == [AUTH_KEY_REMOVED_ERROR]


def test_build_check_passes_without_auth_block(tmp_path: Path):
    _write_fymo_yml(tmp_path, "")
    assert check_auth_key_removed(tmp_path) == []


def test_build_check_passes_with_no_fymo_yml(tmp_path: Path):
    assert check_auth_key_removed(tmp_path) == []


def test_prepare_build_config_fails_on_auth_block(tmp_path: Path):
    """`fymo build`/`fymo dev` both funnel through prepare_build_config;
    the removed key must surface there as a BuildError carrying the same
    migration text, same wiring as the media: check."""
    from fymo.build.prepare import BuildError, prepare_build_config

    _write_fymo_yml(tmp_path, "auth:\n  enabled: true\n")
    with pytest.raises(BuildError, match="fymo generate auth"):
        prepare_build_config(
            tmp_path, tmp_path / "dist", tmp_path / ".fymo", dev=True
        )
