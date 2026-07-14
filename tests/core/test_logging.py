"""fymo.core.logging: structured access logging (human in dev, JSON in prod)."""
import json
import logging
from pathlib import Path

import pytest

from fymo.core.logging import LoggingSettings, resolve_logging_config


def test_access_log_json(caplog):
    from fymo.core.logging import configure, access_log
    configure(json=True)
    with caplog.at_level("INFO", logger="fymo"):
        access_log({"REQUEST_METHOD": "GET", "PATH_INFO": "/x"}, "200 OK", 4.2)
    rec = json.loads(caplog.records[-1].getMessage())
    assert rec["method"] == "GET" and rec["path"] == "/x" and rec["status"] == 200


def test_access_log_json_includes_duration(caplog):
    from fymo.core.logging import configure, access_log
    configure(json=True)
    with caplog.at_level("INFO", logger="fymo"):
        access_log({"REQUEST_METHOD": "POST", "PATH_INFO": "/api/x"}, "500 INTERNAL SERVER ERROR", 12.345)
    rec = json.loads(caplog.records[-1].getMessage())
    assert rec["method"] == "POST"
    assert rec["path"] == "/api/x"
    assert rec["status"] == 500
    assert rec["duration_ms"] == pytest.approx(12.35, abs=0.01)


def test_access_log_human_mode_is_readable_not_json(caplog):
    from fymo.core.logging import configure, access_log
    configure(json=False)
    with caplog.at_level("INFO", logger="fymo"):
        access_log({"REQUEST_METHOD": "GET", "PATH_INFO": "/"}, "200 OK", 1.0)
    message = caplog.records[-1].getMessage()
    # Human mode is not machine-parseable JSON — it's a plain log line.
    with pytest.raises(json.JSONDecodeError):
        json.loads(message)
    assert "GET" in message and "/" in message and "200" in message


def test_access_log_never_includes_cookie_or_body(caplog):
    """PII/secret hygiene: only method, path, status, duration are ever logged."""
    from fymo.core.logging import configure, access_log
    configure(json=True)
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/login",
        "HTTP_COOKIE": "session=super-secret-token",
        "HTTP_AUTHORIZATION": "Bearer super-secret",
        "wsgi.input": "password=hunter2",
    }
    with caplog.at_level("INFO", logger="fymo"):
        access_log(environ, "200 OK", 2.0)
    message = caplog.records[-1].getMessage()
    assert "super-secret" not in message
    assert "hunter2" not in message
    rec = json.loads(message)
    assert set(rec.keys()) == {"method", "path", "status", "duration_ms"}


def test_configure_is_idempotent_no_duplicate_handlers():
    """Repeated configure() calls (e.g. many FymoApp() in tests) must not
    accumulate handlers and duplicate every log line."""
    from fymo.core.logging import configure, logger
    configure(json=True)
    configure(json=True)
    configure(json=False)
    assert len(logger.handlers) == 1


# ---- resolve_logging_config ----


def test_defaults_dev():
    s = resolve_logging_config(dev=True, config=None)
    assert s == LoggingSettings(destination="terminal", file=None, level=logging.INFO, json=False)


def test_defaults_prod():
    s = resolve_logging_config(dev=False, config={})
    assert s.destination == "terminal"
    assert s.json is True  # prod default format is json


def test_file_destination_resolves_relative_to_project_root(tmp_path: Path):
    s = resolve_logging_config(
        dev=False,
        config={"destination": "file", "file": "log/fymo.log"},
        project_root=tmp_path,
    )
    assert s.destination == "file"
    assert s.file == tmp_path / "log" / "fymo.log"


def test_file_destination_absolute_path_kept(tmp_path: Path):
    target = tmp_path / "abs.log"
    s = resolve_logging_config(dev=False, config={"destination": "file", "file": str(target)})
    assert s.file == target


def test_level_and_format_overrides():
    s = resolve_logging_config(dev=False, config={"level": "debug", "format": "text"})
    assert s.level == logging.DEBUG
    assert s.json is False  # explicit format beats prod default


def test_format_json_in_dev():
    s = resolve_logging_config(dev=True, config={"format": "json"})
    assert s.json is True  # explicit format beats dev default


@pytest.mark.parametrize("bad_config, key", [
    ({"destination": "syslog"}, "logging.destination"),
    ({"destination": "file"}, "logging.file"),  # file dest without file path
    ({"level": "verbose"}, "logging.level"),
    ({"format": "xml"}, "logging.format"),
])
def test_invalid_config_fails_fast_naming_the_key(bad_config, key):
    with pytest.raises(ValueError, match=key.replace(".", r"\.")):
        resolve_logging_config(dev=False, config=bad_config)
