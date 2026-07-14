"""Tests for ${VAR} / ${VAR:-default} interpolation in fymo.yml.

Resolved on the raw YAML text before yaml.safe_load parses it, so a
deployment-specific value (e.g. an auth issuer URL) can live directly in
fymo.yml instead of forcing a custom provider class just to read
os.environ. Applies to the whole file, not just one section.
"""
from pathlib import Path

import pytest

from fymo.core.config import ConfigManager
from fymo.core.exceptions import ConfigurationError


def _write_yml(tmp_path: Path, text: str) -> None:
    (tmp_path / "fymo.yml").write_text(text)


def test_required_var_resolves_from_a_real_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("FYMO_TEST_NAME", "acme")
    _write_yml(tmp_path, "name: ${FYMO_TEST_NAME}\n")
    cm = ConfigManager(tmp_path)
    assert cm.get_app_name() == "acme"


def test_required_var_raises_configuration_error_naming_the_var_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("FYMO_TEST_MISSING", raising=False)
    _write_yml(tmp_path, "name: ${FYMO_TEST_MISSING}\n")
    with pytest.raises(ConfigurationError, match="FYMO_TEST_MISSING"):
        ConfigManager(tmp_path)


def test_default_falls_back_when_var_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("FYMO_TEST_OPTIONAL", raising=False)
    _write_yml(tmp_path, "name: ${FYMO_TEST_OPTIONAL:-fallback}\n")
    cm = ConfigManager(tmp_path)
    assert cm.get_app_name() == "fallback"


def test_default_is_ignored_when_var_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("FYMO_TEST_OPTIONAL", "real-value")
    _write_yml(tmp_path, "name: ${FYMO_TEST_OPTIONAL:-fallback}\n")
    cm = ConfigManager(tmp_path)
    assert cm.get_app_name() == "real-value"


def test_empty_default_resolves_to_empty_string(tmp_path, monkeypatch):
    monkeypatch.delenv("FYMO_TEST_EMPTY", raising=False)
    _write_yml(tmp_path, 'name: "${FYMO_TEST_EMPTY:-}"\n')
    cm = ConfigManager(tmp_path)
    assert cm.get_app_name() == ""


def test_interpolation_applies_to_the_whole_file_not_just_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("FYMO_TEST_DESC", "hello world")
    _write_yml(tmp_path, "name: app\ndescription: ${FYMO_TEST_DESC}\n")
    cm = ConfigManager(tmp_path)
    assert cm.get("description") == "hello world"


def test_interpolation_inside_nested_auth_providers_section(tmp_path, monkeypatch):
    monkeypatch.setenv("FYMO_TEST_ISSUER", "https://issuer.example.com")
    _write_yml(
        tmp_path,
        "auth:\n"
        "  providers:\n"
        "    - class: app.lib.SomeProvider\n"
        "      issuer: ${FYMO_TEST_ISSUER}\n",
    )
    cm = ConfigManager(tmp_path)
    providers = cm.get_auth_config()["providers"]
    assert providers[0]["issuer"] == "https://issuer.example.com"


def test_no_placeholders_leaves_config_untouched(tmp_path):
    _write_yml(tmp_path, "name: plain-app\n")
    cm = ConfigManager(tmp_path)
    assert cm.get_app_name() == "plain-app"
