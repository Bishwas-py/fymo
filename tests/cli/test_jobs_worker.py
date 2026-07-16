"""Tests for the `fymo jobs-worker` CLI command."""
import logging
import os
from pathlib import Path

import pytest

import fymo.core.logging as fymo_logging
from fymo.cli.commands.jobs_worker import run_jobs_worker
from fymo.jobs import reset_job_provider
from fymo.storage import reset_storage_provider


@pytest.fixture(autouse=True)
def _restore_fymo_dev():
    """run_jobs_worker(dev=True) writes FYMO_DEV=1 into this process's real
    environment (that's its documented job). monkeypatch.delenv on a var
    that was already absent registers no undo, so without an explicit
    snapshot/restore here the flag would leak into every later test in the
    suite and silently flip middleware defaults (rate limiting, HSTS) to
    their dev behavior."""
    before = os.environ.get("FYMO_DEV")
    yield
    if before is None:
        os.environ.pop("FYMO_DEV", None)
    else:
        os.environ["FYMO_DEV"] = before


@pytest.fixture(autouse=True)
def _reset():
    reset_job_provider()
    reset_storage_provider()
    yield
    reset_job_provider()
    reset_storage_provider()


@pytest.fixture(autouse=True)
def _reset_configured_handler():
    """run_jobs_worker calls configure() before its SystemExit in several
    tests here, installing a root handler + level with no cleanup of its
    own — process-global logging state that must not leak between tests
    (or into other test files)."""
    yield
    root = logging.getLogger()
    if fymo_logging._installed_handler is not None:
        root.removeHandler(fymo_logging._installed_handler)
        fymo_logging._installed_handler.close()
        fymo_logging._installed_handler = None
    root.setLevel(logging.WARNING)


def test_reports_a_clear_error_for_the_default_threaded_provider(tmp_path: Path, capsys):
    """No fymo.yml `jobs:` section => ThreadedJobProvider, which has no
    separate worker process to run — the CLI should exit non-zero with a
    clear message, not crash with a raw traceback."""
    with pytest.raises(SystemExit) as exc_info:
        run_jobs_worker(tmp_path)

    assert exc_info.value.code == 1
    assert "has no separate worker process" in capsys.readouterr().out


def test_reports_a_clear_error_when_procrastinate_is_configured_but_database_url_is_missing(
    tmp_path: Path, capsys, monkeypatch
):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    (tmp_path / "fymo.yml").write_text("jobs:\n  provider: procrastinate\n")

    with pytest.raises(SystemExit) as exc_info:
        run_jobs_worker(tmp_path)

    assert exc_info.value.code == 1
    assert "DATABASE_URL" in capsys.readouterr().out


def test_jobs_worker_configures_logging_from_yml(tmp_path, monkeypatch):
    """The worker process must honor fymo.yml's logging section — it was
    previously a logging black box (no configure() call at all)."""
    log_file = tmp_path / "worker.log"
    (tmp_path / "fymo.yml").write_text(
        "name: W\n"
        "logging:\n"
        "  destination: file\n"
        f"  file: {log_file}\n"
        "  format: json\n"
    )
    (tmp_path / "app" / "jobs").mkdir(parents=True)

    # The default threaded provider has no separate worker loop — it exits
    # with SystemExit(1) AFTER configuration, which is all this test needs.
    with pytest.raises(SystemExit):
        run_jobs_worker(tmp_path)
    assert fymo_logging._installed_handler is not None
    assert isinstance(fymo_logging._installed_handler, logging.FileHandler)


def test_jobs_worker_loads_dotenv_before_config_manager_when_dev(tmp_path, monkeypatch):
    """.env must be loaded (dev-only) before ConfigManager parses fymo.yml,
    same ordering as FymoApp.__init__. Proven by making fymo.yml's `name`
    require a var only .env provides: if load_dotenv ran after ConfigManager
    (or not at all), ${FYMO_TEST_WORKER_DOTENV} would be unresolved and
    ConfigManager would raise ConfigurationError instead of the expected
    SystemExit(1) from the (successfully parsed) default threaded provider,
    so pytest.raises(SystemExit) below would fail if the ordering broke."""
    monkeypatch.delenv("FYMO_TEST_WORKER_DOTENV", raising=False)
    monkeypatch.setenv("FYMO_DEV", "1")
    (tmp_path / ".env").write_text("FYMO_TEST_WORKER_DOTENV=loaded\n")
    (tmp_path / "fymo.yml").write_text("name: ${FYMO_TEST_WORKER_DOTENV}\n")

    # Default threaded provider (no `jobs:` section) exits with SystemExit(1)
    # quickly and predictably, same mechanism the other tests in this file
    # rely on, but only once fymo.yml parses at all.
    with pytest.raises(SystemExit):
        run_jobs_worker(tmp_path)

    assert os.environ["FYMO_TEST_WORKER_DOTENV"] == "loaded"


def test_jobs_worker_ignores_dotenv_when_not_dev(tmp_path, monkeypatch):
    monkeypatch.delenv("FYMO_TEST_WORKER_DOTENV_PROD", raising=False)
    monkeypatch.delenv("FYMO_DEV", raising=False)
    (tmp_path / ".env").write_text("FYMO_TEST_WORKER_DOTENV_PROD=should-not-load\n")

    with pytest.raises(SystemExit):
        run_jobs_worker(tmp_path)

    assert "FYMO_TEST_WORKER_DOTENV_PROD" not in os.environ


def test_jobs_worker_initializes_storage_when_configured(tmp_path: Path):
    """Issue #31: a job running in the worker process (a separate OS process
    from the web process) needs fymo.storage.get_storage_provider() to work
    too, the same way it already needs init_broadcasts() to make publish()
    work here. The default threaded provider still exits with SystemExit(1)
    (no separate worker loop), but storage must be wired up before that."""
    (tmp_path / "fymo.yml").write_text("storage:\n  provider: local\n")

    with pytest.raises(SystemExit):
        run_jobs_worker(tmp_path)

    from fymo.storage import get_storage_provider
    from fymo.storage.providers.local import LocalStorageProvider

    assert isinstance(get_storage_provider(), LocalStorageProvider)


def test_jobs_worker_leaves_storage_uninitialized_when_not_configured(tmp_path: Path):
    """No storage: section => no default provider (same guarantee as
    FymoApp itself); get_storage_provider() must still raise."""
    with pytest.raises(SystemExit):
        run_jobs_worker(tmp_path)

    from fymo.storage import get_storage_provider

    with pytest.raises(RuntimeError, match="storage is not initialized"):
        get_storage_provider()


def test_dev_flag_sets_fymo_dev_and_loads_dotenv(tmp_path, monkeypatch):
    """Issue #44: `fymo jobs-worker --dev` must be authoritative about dev
    mode (set FYMO_DEV=1 itself, same treatment fymo dev got in #26) so a
    developer never has to prefix the command with FYMO_DEV=1 by hand.
    Proven the same way as the FYMO_DEV-env test above: fymo.yml only
    parses if .env got loaded first."""
    monkeypatch.delenv("FYMO_TEST_WORKER_DEVFLAG", raising=False)
    monkeypatch.delenv("FYMO_DEV", raising=False)
    (tmp_path / ".env").write_text("FYMO_TEST_WORKER_DEVFLAG=loaded\n")
    (tmp_path / "fymo.yml").write_text("name: ${FYMO_TEST_WORKER_DEVFLAG}\n")

    with pytest.raises(SystemExit):
        run_jobs_worker(tmp_path, dev=True)

    assert os.environ.get("FYMO_DEV") == "1"
    assert os.environ["FYMO_TEST_WORKER_DEVFLAG"] == "loaded"


def test_without_dev_flag_stays_prod_and_ignores_dotenv(tmp_path, monkeypatch):
    """Default must remain off: a forgotten flag on a prod worker must not
    silently start reading a stray .env lying around in the container."""
    monkeypatch.delenv("FYMO_TEST_WORKER_NOFLAG", raising=False)
    monkeypatch.delenv("FYMO_DEV", raising=False)
    (tmp_path / ".env").write_text("FYMO_TEST_WORKER_NOFLAG=should-not-load\n")

    with pytest.raises(SystemExit):
        run_jobs_worker(tmp_path)

    assert "FYMO_TEST_WORKER_NOFLAG" not in os.environ
    assert os.environ.get("FYMO_DEV") != "1"


def test_dev_flag_false_does_not_override_existing_fymo_dev_env(tmp_path, monkeypatch):
    """Omitting --dev means "no opinion", not "force prod": FYMO_DEV=1
    exported in the shell must keep working exactly as before the flag
    existed (backward compatibility with every current setup)."""
    monkeypatch.delenv("FYMO_TEST_WORKER_ENVSTILL", raising=False)
    monkeypatch.setenv("FYMO_DEV", "1")
    (tmp_path / ".env").write_text("FYMO_TEST_WORKER_ENVSTILL=loaded\n")
    (tmp_path / "fymo.yml").write_text("name: ${FYMO_TEST_WORKER_ENVSTILL}\n")

    with pytest.raises(SystemExit):
        run_jobs_worker(tmp_path)

    assert os.environ["FYMO_TEST_WORKER_ENVSTILL"] == "loaded"
