"""Tests for the `fymo jobs-worker` CLI command."""
from pathlib import Path

import pytest

from fymo.cli.commands.jobs_worker import run_jobs_worker
from fymo.jobs import reset_job_provider


@pytest.fixture(autouse=True)
def _reset():
    reset_job_provider()
    yield
    reset_job_provider()


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
    import logging as _logging
    import fymo.core.logging as fymo_logging

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
    from fymo.cli.commands.jobs_worker import run_jobs_worker
    try:
        with pytest.raises(SystemExit):
            run_jobs_worker(tmp_path)
        assert fymo_logging._installed_handler is not None
        assert isinstance(fymo_logging._installed_handler, _logging.FileHandler)
    finally:
        root = _logging.getLogger()
        if fymo_logging._installed_handler is not None:
            root.removeHandler(fymo_logging._installed_handler)
            fymo_logging._installed_handler.close()
            fymo_logging._installed_handler = None
        root.setLevel(_logging.WARNING)
