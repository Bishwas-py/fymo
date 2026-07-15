"""Tests for load_dotenv: parses .env into os.environ, dev-gated at the
call sites (FymoApp.__init__, run_jobs_worker), real env vars always win.
"""
import os
from pathlib import Path

from fymo.core.config import load_dotenv


def _write_dotenv(tmp_path: Path, text: str) -> None:
    (tmp_path / ".env").write_text(text)


def test_loads_simple_key_value_pairs(tmp_path, monkeypatch):
    monkeypatch.delenv("FYMO_TEST_DOTENV_A", raising=False)
    _write_dotenv(tmp_path, "FYMO_TEST_DOTENV_A=hello\n")
    load_dotenv(tmp_path)
    assert os.environ["FYMO_TEST_DOTENV_A"] == "hello"


def test_real_env_var_always_wins_over_dotenv(tmp_path, monkeypatch):
    monkeypatch.setenv("FYMO_TEST_DOTENV_B", "from-shell")
    _write_dotenv(tmp_path, "FYMO_TEST_DOTENV_B=from-dotenv\n")
    load_dotenv(tmp_path)
    assert os.environ["FYMO_TEST_DOTENV_B"] == "from-shell"


def test_skips_blank_lines_and_comments(tmp_path, monkeypatch):
    monkeypatch.delenv("FYMO_TEST_DOTENV_C", raising=False)
    _write_dotenv(tmp_path, "\n# a comment\n\nFYMO_TEST_DOTENV_C=value\n# trailing comment\n")
    load_dotenv(tmp_path)
    assert os.environ["FYMO_TEST_DOTENV_C"] == "value"


def test_strips_matching_surrounding_quotes(tmp_path, monkeypatch):
    monkeypatch.delenv("FYMO_TEST_DOTENV_D", raising=False)
    monkeypatch.delenv("FYMO_TEST_DOTENV_E", raising=False)
    _write_dotenv(tmp_path, 'FYMO_TEST_DOTENV_D="double quoted"\nFYMO_TEST_DOTENV_E=\'single quoted\'\n')
    load_dotenv(tmp_path)
    assert os.environ["FYMO_TEST_DOTENV_D"] == "double quoted"
    assert os.environ["FYMO_TEST_DOTENV_E"] == "single quoted"


def test_ignores_lines_without_equals_sign(tmp_path, monkeypatch):
    _write_dotenv(tmp_path, "not a valid line\nFYMO_TEST_DOTENV_F=value\n")
    load_dotenv(tmp_path)
    assert os.environ["FYMO_TEST_DOTENV_F"] == "value"


def test_missing_dotenv_file_is_a_silent_noop(tmp_path):
    # tmp_path has no .env at all; must not raise.
    load_dotenv(tmp_path)


def test_strips_whitespace_around_key_and_value(tmp_path, monkeypatch):
    monkeypatch.delenv("FYMO_TEST_DOTENV_G", raising=False)
    _write_dotenv(tmp_path, "  FYMO_TEST_DOTENV_G   =   spaced value  \n")
    load_dotenv(tmp_path)
    assert os.environ["FYMO_TEST_DOTENV_G"] == "spaced value"


import pytest

from fymo.core.server import FymoApp


def _write_fake_sidecar(tmp_path: Path) -> None:
    """FymoApp always requires dist/sidecar.mjs (no dev-mode bypass). Same
    minimal length-prefixed-JSON-IPC stub as test_logging.py, only needed by
    the one test below that must get past full construction to inspect
    config_manager; the others assert on os.environ before that point and
    don't need a working sidecar."""
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


def test_fymo_app_loads_dotenv_in_dev_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("FYMO_TEST_DOTENV_APP", raising=False)
    monkeypatch.setenv("FYMO_SECRET", "x" * 32)
    _write_dotenv(tmp_path, "FYMO_TEST_DOTENV_APP=loaded\n")
    # No dist/ here, so construction fails past the point load_dotenv runs;
    # os.environ is already updated by then, which is all this test checks.
    with pytest.raises(RuntimeError, match="dist/ not found"):
        FymoApp(project_root=tmp_path, dev=True)
    assert os.environ["FYMO_TEST_DOTENV_APP"] == "loaded"


def test_fymo_app_ignores_dotenv_in_prod_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("FYMO_TEST_DOTENV_PROD", raising=False)
    monkeypatch.setenv("FYMO_SECRET", "x" * 32)
    _write_dotenv(tmp_path, "FYMO_TEST_DOTENV_PROD=should-not-load\n")
    with pytest.raises(RuntimeError, match="dist/ not found"):
        FymoApp(project_root=tmp_path, dev=False)
    assert "FYMO_TEST_DOTENV_PROD" not in os.environ


def test_fymo_app_dotenv_can_be_read_by_fymo_yml_interpolation(tmp_path, monkeypatch):
    monkeypatch.delenv("FYMO_TEST_DOTENV_YML", raising=False)
    monkeypatch.setenv("FYMO_SECRET", "x" * 32)
    _write_dotenv(tmp_path, "FYMO_TEST_DOTENV_YML=from-dotenv\n")
    # Explicit (empty) routes section: without it the router falls back to
    # treating the whole fymo.yml as its routes mapping and chokes on
    # top-level scalar keys like `name`. Unrelated to .env; just the
    # minimal scaffolding FymoApp/Router need to construct at all.
    (tmp_path / "fymo.yml").write_text(
        "name: ${FYMO_TEST_DOTENV_YML}\nroutes: {}\n"
    )
    _write_fake_sidecar(tmp_path)
    app = FymoApp(project_root=tmp_path, dev=True)
    try:
        assert app.config_manager.get_app_name() == "from-dotenv"
    finally:
        if app.sidecar:
            app.sidecar.stop()
