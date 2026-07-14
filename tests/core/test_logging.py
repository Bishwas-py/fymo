"""fymo.core.logging: structured access logging (human in dev, JSON in prod)."""
import json
import logging
from pathlib import Path

import pytest

from fymo.core.logging import LoggingSettings, resolve_logging_config


def test_access_log_json(caplog):
    from fymo.core.logging import configure, access_log
    configure(dev=False)  # prod -> json mode
    with caplog.at_level("INFO", logger="fymo"):
        access_log({"REQUEST_METHOD": "GET", "PATH_INFO": "/x"}, "200 OK", 4.2)
    rec = json.loads(caplog.records[-1].getMessage())
    assert rec["method"] == "GET" and rec["path"] == "/x" and rec["status"] == 200


def test_access_log_json_includes_duration(caplog):
    from fymo.core.logging import configure, access_log
    configure(dev=False)  # prod -> json mode
    with caplog.at_level("INFO", logger="fymo"):
        access_log({"REQUEST_METHOD": "POST", "PATH_INFO": "/api/x"}, "500 INTERNAL SERVER ERROR", 12.345)
    rec = json.loads(caplog.records[-1].getMessage())
    assert rec["method"] == "POST"
    assert rec["path"] == "/api/x"
    assert rec["status"] == 500
    assert rec["duration_ms"] == pytest.approx(12.35, abs=0.01)


def test_access_log_human_mode_is_readable_not_json(caplog):
    from fymo.core.logging import configure, access_log
    configure(dev=True)  # dev -> text mode
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
    configure(dev=False)  # prod -> json mode
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


# NOTE: the old test_configure_is_idempotent_no_duplicate_handlers (which
# asserted len(logger.handlers) == 1 on the "fymo" logger) was removed: the
# handler now lives on the ROOT logger, and the "fymo" logger permanently
# holds only its NullHandler, so the old assertion would pass vacuously.
# Idempotency is covered by test_reconfigure_installs_exactly_one_handler.


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


import json as jsonlib

from fymo.core.logging import access_log, configure
import fymo.core.logging as fymo_logging


@pytest.fixture(autouse=True)
def _reset_configured_handler():
    """Each test starts with no fymo-installed root handler and leaves none
    behind — configure() mutates process-global logging state."""
    yield
    root = logging.getLogger()
    if fymo_logging._installed_handler is not None:
        root.removeHandler(fymo_logging._installed_handler)
        fymo_logging._installed_handler.close()
        fymo_logging._installed_handler = None
    root.setLevel(logging.WARNING)  # stdlib default


def _fymo_handlers() -> list:
    return [h for h in logging.getLogger().handlers if h is fymo_logging._installed_handler]


# ---------------- configure(): destinations ----------------


def test_file_destination_writes_lines(tmp_path: Path):
    log_file = tmp_path / "log" / "fymo.log"  # parent dir doesn't exist yet
    configure(dev=True, config={"destination": "file", "file": str(log_file)})
    access_log({"REQUEST_METHOD": "GET", "PATH_INFO": "/x"}, "200 OK", 1.5)
    content = log_file.read_text()
    assert "GET /x 200 1.5ms" in content


def test_terminal_destination_uses_stream_handler():
    configure(dev=True, config={})
    (handler,) = _fymo_handlers()
    assert isinstance(handler, logging.StreamHandler)
    assert not isinstance(handler, logging.FileHandler)


# ---------------- configure(): root capture + format matrix ----------------


def test_app_logger_records_are_captured_and_wrapped_json(tmp_path: Path):
    log_file = tmp_path / "app.log"
    configure(dev=False, config={"destination": "file", "file": str(log_file)})  # prod -> json
    logging.getLogger("app.payments").info("charge ok")
    line = log_file.read_text().strip().splitlines()[-1]
    parsed = jsonlib.loads(line)
    assert parsed == {"logger": "app.payments", "level": "INFO", "message": "charge ok"}


def test_fymo_json_lines_pass_through_unwrapped(tmp_path: Path):
    log_file = tmp_path / "app.log"
    configure(dev=False, config={"destination": "file", "file": str(log_file)})
    access_log({"REQUEST_METHOD": "GET", "PATH_INFO": "/y"}, "404 Not Found", 2.0)
    line = log_file.read_text().strip().splitlines()[-1]
    parsed = jsonlib.loads(line)
    assert parsed == {"method": "GET", "path": "/y", "status": 404, "duration_ms": 2.0}


def test_app_logger_records_text_format(tmp_path: Path):
    log_file = tmp_path / "app.log"
    configure(dev=True, config={"destination": "file", "file": str(log_file)})  # dev -> text
    logging.getLogger("app.payments").warning("low balance")
    assert "WARNING app.payments: low balance" in log_file.read_text()


def test_exception_traceback_included_in_json(tmp_path: Path):
    log_file = tmp_path / "app.log"
    configure(dev=False, config={"destination": "file", "file": str(log_file)})
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logging.getLogger("app.x").error("failed", exc_info=True)
    parsed = jsonlib.loads(log_file.read_text().strip().splitlines()[-1])
    assert "RuntimeError: boom" in parsed["exc_info"]


# ---------------- configure(): level ----------------


def test_level_filters_below_threshold(tmp_path: Path):
    log_file = tmp_path / "app.log"
    configure(dev=True, config={"destination": "file", "file": str(log_file), "level": "warning"})
    logging.getLogger("app.x").info("hidden")
    logging.getLogger("app.x").warning("shown")
    content = log_file.read_text()
    assert "hidden" not in content
    assert "shown" in content


def test_debug_level_shows_debug(tmp_path: Path):
    log_file = tmp_path / "app.log"
    configure(dev=True, config={"destination": "file", "file": str(log_file), "level": "debug"})
    logging.getLogger("app.x").debug("dbg")
    assert "dbg" in log_file.read_text()


# ---------------- configure(): idempotency + coexistence ----------------


def test_reconfigure_installs_exactly_one_handler():
    configure(dev=True)
    configure(dev=True)
    configure(dev=False)
    assert len(_fymo_handlers()) == 1


def test_reconfigure_preserves_foreign_root_handlers():
    foreign = logging.NullHandler()
    root = logging.getLogger()
    root.addHandler(foreign)
    try:
        configure(dev=True)
        configure(dev=True)
        assert foreign in root.handlers
    finally:
        root.removeHandler(foreign)


def test_import_without_configure_emits_nothing(capsys):
    # The "fymo" logger has a NullHandler and nothing is on root from us.
    logging.getLogger("fymo").info("quiet")
    captured = capsys.readouterr()
    assert "quiet" not in captured.out + captured.err


@pytest.mark.usefixtures("node_available")
def test_fymo_app_configures_logging_from_yml(tmp_path: Path, monkeypatch):
    """End-to-end config plumbing: a fymo.yml logging section reaches the
    root handler via FymoApp construction. Uses a minimal project dir —
    FymoApp tolerates a missing dist/ at construction time. NOTE for the
    implementer: if FymoApp.__init__ turns out to require more scaffolding
    (e.g. app/templates existing), create the minimal empty dirs here — do
    NOT weaken the assertion; the point is that construction alone routes
    logs per fymo.yml."""
    log_file = tmp_path / "log" / "app.log"
    (tmp_path / "fymo.yml").write_text(
        "name: LogTest\n"
        # Explicit (empty) routes section: without it the router falls back
        # to treating the whole fymo.yml as its routes mapping, and chokes
        # trying to split top-level scalar keys like `name` as
        # "controller.action" strings. Unrelated to logging; just the
        # minimal scaffolding FymoApp/Router need to construct at all.
        "routes: {}\n"
        "logging:\n"
        "  destination: file\n"
        f"  file: {log_file}\n"
        "  format: json\n"
    )
    # FymoApp always requires dist/sidecar.mjs (no dev-mode bypass) — hand-roll
    # the tiniest possible sidecar implementing just enough of the
    # length-prefixed JSON IPC protocol (see fymo/core/sidecar.py) to answer
    # the startup ping. No real esbuild/BuildPipeline needed since this test
    # never renders anything, only exercises the logging config plumbing.
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "sidecar.mjs").write_text(
        "let buf = Buffer.alloc(0);\n"
        "process.stdin.on('data', (chunk) => {\n"
        "  buf = Buffer.concat([buf, chunk]);\n"
        "  while (buf.length >= 4) {\n"
        "    const len = buf.readUInt32BE(0);\n"
        "    if (buf.length < 4 + len) break;\n"
        "    const msg = JSON.parse(buf.slice(4, 4 + len).toString('utf8'));\n"
        "    buf = buf.slice(4 + len);\n"
        "    const replyBody = Buffer.from(JSON.stringify({ ok: true, id: msg.id }), 'utf8');\n"
        "    const header = Buffer.alloc(4);\n"
        "    header.writeUInt32BE(replyBody.length, 0);\n"
        "    process.stdout.write(Buffer.concat([header, replyBody]));\n"
        "  }\n"
        "});\n"
    )
    from fymo.core.server import FymoApp
    app = FymoApp(tmp_path, dev=True)
    try:
        logging.getLogger("app.smoke").info("hello file")
    finally:
        if app.sidecar:
            app.sidecar.stop()
    parsed = jsonlib.loads(log_file.read_text().strip().splitlines()[-1])
    assert parsed["message"] == "hello file"


def test_fymo_app_invalid_logging_config_fails_at_startup(tmp_path: Path):
    (tmp_path / "fymo.yml").write_text(
        "name: LogTest\nlogging:\n  destination: syslog\n"
    )
    from fymo.core.server import FymoApp
    with pytest.raises(ValueError, match=r"logging\.destination"):
        FymoApp(tmp_path, dev=True)
