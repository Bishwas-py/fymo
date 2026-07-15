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
