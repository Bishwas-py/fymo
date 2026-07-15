"""Tests for the `fymo jobs-worker` CLI command."""
import logging
from pathlib import Path

import pytest

import fymo.core.logging as fymo_logging
from fymo.cli.commands.jobs_worker import run_jobs_worker
from fymo.jobs import reset_job_provider
from fymo.storage import reset_storage_provider


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
