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


# ---------------- server.py explicit_optin wiring ----------------


def test_fymo_app_explicit_optin_string_false_from_interpolation_resolves_false(
    tmp_path: Path, monkeypatch,
):
    """Regression for issue #30: remote.explicit_optin: ${VAR} interpolates
    to the plain string "false" (see fymo.core.config._yaml_quote); a bare
    bool("false") would truthy-coerce this to True and silently enable the
    dispatch gate the config asked to leave off.

    FymoApp construction reaches _explicit_optin resolution well before it
    needs dist/ (that check is the last thing __init__ does), so a bare
    fymo.yml with an empty routes: section is enough to exercise this
    without a real build. routes: {} avoids the router trying to treat the
    whole fymo.yml as a routes mapping and choking on top-level scalar
    keys, unrelated to this bug, just the minimal scaffolding FymoApp's
    constructor needs to get as far as raising on the missing dist/.
    """
    monkeypatch.setenv("FYMO_TEST_EXPLICIT_OPTIN", "false")
    _write_yml(
        tmp_path,
        "name: OptinTest\nroutes: {}\nremote:\n  explicit_optin: ${FYMO_TEST_EXPLICIT_OPTIN}\n",
    )
    from fymo.core.server import FymoApp
    from fymo.remote import router as remote_router

    with pytest.raises(RuntimeError, match="dist/ not found"):
        FymoApp(tmp_path, dev=True)
    assert remote_router._explicit_optin is False


# ---------------- server.py auth.enabled wiring ----------------


def test_fymo_app_auth_enabled_string_false_from_interpolation_stays_off(
    tmp_path: Path, monkeypatch,
):
    """Regression for issue #30: auth.enabled: ${VAR} interpolating to the
    string "false" must not run auth initialization. A bare truthy check
    on auth_cfg.get("enabled") would treat any non-empty string as on.

    _init_auth is monkeypatched to raise if called at all, since FymoApp's
    __init__ raises on missing dist/ before returning, so there is no
    instance left afterward to inspect a self.auth_enabled attribute on.
    Whether _init_auth ran is the only observable signal here.
    """
    monkeypatch.setenv("FYMO_TEST_AUTH_ENABLED", "false")
    _write_yml(
        tmp_path,
        "name: AuthTest\nroutes: {}\nauth:\n  enabled: ${FYMO_TEST_AUTH_ENABLED}\n",
    )
    from fymo.core.server import FymoApp

    def _fail_if_called(self, auth_cfg):
        raise AssertionError("auth should have stayed off")

    monkeypatch.setattr(FymoApp, "_init_auth", _fail_if_called)

    with pytest.raises(RuntimeError, match="dist/ not found"):
        FymoApp(tmp_path, dev=True)


def test_fymo_app_auth_enabled_raises_configuration_error_on_garbage(
    tmp_path: Path, monkeypatch,
):
    monkeypatch.setenv("FYMO_TEST_AUTH_ENABLED_GARBAGE", "enabeld")
    _write_yml(
        tmp_path,
        "name: AuthTest\nroutes: {}\nauth:\n  enabled: ${FYMO_TEST_AUTH_ENABLED_GARBAGE}\n",
    )
    from fymo.core.server import FymoApp

    with pytest.raises(ConfigurationError, match="auth.enabled"):
        FymoApp(tmp_path, dev=True)
