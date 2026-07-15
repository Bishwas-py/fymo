"""Tests for typed values flowing through fymo.yml.

${VAR} interpolation always produces a plain YAML string (see
fymo.core.config._yaml_quote, a deliberate anti-injection fix, not a
typing decision), so a consumer that needs a real int/bool must cast
explicitly instead of trusting the YAML type. See issue #30.
"""
from pathlib import Path

import pytest

from fymo.core.config import ConfigManager, parse_bool
from fymo.core.exceptions import ConfigurationError


def _write_yml(tmp_path: Path, text: str) -> None:
    (tmp_path / "fymo.yml").write_text(text)


# ---------------- parse_bool ----------------


def test_parse_bool_passes_through_real_bool_true():
    assert parse_bool(True, field="x") is True


def test_parse_bool_passes_through_real_bool_false():
    assert parse_bool(False, field="x") is False


def test_parse_bool_accepts_true_string_case_and_whitespace_insensitive():
    assert parse_bool("true", field="x") is True
    assert parse_bool("TRUE", field="x") is True
    assert parse_bool(" True ", field="x") is True


def test_parse_bool_accepts_false_string_case_and_whitespace_insensitive():
    assert parse_bool("false", field="x") is False
    assert parse_bool("FALSE", field="x") is False
    assert parse_bool(" False ", field="x") is False


def test_parse_bool_rejects_yes_no():
    with pytest.raises(ConfigurationError, match="rate_limit.enabled"):
        parse_bool("yes", field="rate_limit.enabled")


def test_parse_bool_rejects_numeric_strings():
    with pytest.raises(ConfigurationError, match="rate_limit.enabled"):
        parse_bool("1", field="rate_limit.enabled")


def test_parse_bool_rejects_empty_string():
    with pytest.raises(ConfigurationError, match="rate_limit.enabled"):
        parse_bool("", field="rate_limit.enabled")


def test_parse_bool_rejects_non_string_non_bool():
    with pytest.raises(ConfigurationError, match="rate_limit.enabled"):
        parse_bool(1, field="rate_limit.enabled")
