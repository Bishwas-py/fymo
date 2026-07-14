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
    _write_yml(tmp_path, "name: ${FYMO_TEST_EMPTY:-}\n")
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


# YAML-structure injection through an env var's value


def test_env_var_value_containing_yaml_structure_stays_a_literal_string(tmp_path, monkeypatch):
    """A substituted value must never be interpreted as YAML structure, no
    matter what it contains: a value with a newline followed by something
    that looks like a new top-level key must not add that key."""
    monkeypatch.setenv("INJECT", "harmless\nadmin: true")
    _write_yml(tmp_path, "name: ${INJECT}\n")
    cm = ConfigManager(tmp_path)
    assert cm.get_app_name() == "harmless\nadmin: true"
    assert "admin" not in cm.to_dict()


def test_env_var_value_with_colon_and_dashes_stays_a_literal_string(tmp_path, monkeypatch):
    monkeypatch.setenv("INJECT2", "a: b\n- c\n- d")
    _write_yml(tmp_path, "description: ${INJECT2}\n")
    cm = ConfigManager(tmp_path)
    assert cm.get("description") == "a: b\n- c\n- d"
    assert "a" not in cm.to_dict()


# nested and malformed placeholders


def test_nested_placeholder_inside_a_default_is_resolved(tmp_path, monkeypatch):
    monkeypatch.delenv("FYMO_TEST_A", raising=False)
    monkeypatch.setenv("FYMO_TEST_B", "inner-value")
    _write_yml(tmp_path, "name: ${FYMO_TEST_A:-${FYMO_TEST_B}}\n")
    cm = ConfigManager(tmp_path)
    assert cm.get_app_name() == "inner-value"


def test_nested_placeholder_inside_a_default_is_skipped_when_outer_var_is_set(tmp_path, monkeypatch):
    """The inner ${FYMO_TEST_B} must not even need to resolve when the outer
    var is already set: the default (and anything nested in it) is only
    evaluated as a fallback."""
    monkeypatch.setenv("FYMO_TEST_A", "outer-value")
    monkeypatch.delenv("FYMO_TEST_B", raising=False)
    _write_yml(tmp_path, "name: ${FYMO_TEST_A:-${FYMO_TEST_B}}\n")
    cm = ConfigManager(tmp_path)
    assert cm.get_app_name() == "outer-value"


def test_default_containing_literal_braces_is_not_truncated_at_the_first_close_brace(tmp_path, monkeypatch):
    monkeypatch.delenv("FYMO_TEST_JSONLIKE", raising=False)
    _write_yml(tmp_path, 'name: ${FYMO_TEST_JSONLIKE:-{"a":1}}\n')
    cm = ConfigManager(tmp_path)
    assert cm.get_app_name() == '{"a":1}'


def test_unterminated_placeholder_raises_a_clear_configuration_error(tmp_path):
    _write_yml(tmp_path, "name: ${FYMO_TEST_UNCLOSED\n")
    with pytest.raises(ConfigurationError, match="unterminated"):
        ConfigManager(tmp_path)


def test_malformed_placeholder_name_raises_a_clear_configuration_error(tmp_path):
    _write_yml(tmp_path, "name: ${123bad}\n")
    with pytest.raises(ConfigurationError, match="malformed"):
        ConfigManager(tmp_path)
