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
