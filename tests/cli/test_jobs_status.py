"""Tests for the `fymo jobs-status` CLI command."""
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from fymo.cli.commands.jobs_status import run_jobs_status
from fymo.jobs import reset_job_provider
from fymo.jobs.providers.base import BaseJobProvider, JobRecord


class StubTrackingProvider(BaseJobProvider):
    """A provider that tracks job state, referenced from fymo.yml by its
    dotted path (same escape hatch test_registry.py exercises) so the CLI
    is tested through the real config -> registry -> provider path."""

    id = "stub-tracking"
    last_limit: Optional[int] = None

    def job_counts(self) -> Dict[str, int]:
        return {"todo": 2, "doing": 1, "succeeded": 40, "failed": 3}

    def list_recent_jobs(self, limit: int = 10) -> List[JobRecord]:
        type(self).last_limit = limit
        return [
            JobRecord(
                id="42", task_name="send_email", status="succeeded",
                queued_at=datetime(2026, 7, 16, 10, 0, 0, tzinfo=timezone.utc),
            ),
            JobRecord(id="41", task_name="crunch", status="todo", queued_at=None),
        ]


class StubCountsOnlyProvider(BaseJobProvider):
    """Counts but no per-job listing; the CLI must degrade gracefully."""

    id = "stub-counts-only"

    def job_counts(self) -> Dict[str, int]:
        return {"todo": 0, "doing": 0}


class StubClosableProvider(BaseJobProvider):
    """Records close() so the CLI's connection-release contract is testable."""

    id = "stub-closable"
    closed = False

    def job_counts(self) -> Dict[str, int]:
        return {"todo": 0}

    def close(self) -> None:
        type(self).closed = True


@pytest.fixture(autouse=True)
def _restore_fymo_dev():
    """Same reasoning as tests/cli/test_jobs_worker.py: run_jobs_status(dev=True)
    writes FYMO_DEV=1 into the real environment, and monkeypatch can't undo
    a set on a var that was absent before the test."""
    before = os.environ.get("FYMO_DEV")
    yield
    if before is None:
        os.environ.pop("FYMO_DEV", None)
    else:
        os.environ["FYMO_DEV"] = before


@pytest.fixture(autouse=True)
def _reset():
    reset_job_provider()
    StubTrackingProvider.last_limit = None
    StubClosableProvider.closed = False
    yield
    reset_job_provider()


def test_reports_a_clear_error_for_the_default_threaded_provider(tmp_path: Path, capsys):
    """No fymo.yml `jobs:` section => ThreadedJobProvider, which doesn't
    track job state, so the CLI should exit non-zero saying so, not print
    an empty (and misleading) report."""
    with pytest.raises(SystemExit) as exc_info:
        run_jobs_status(tmp_path)

    assert exc_info.value.code == 1
    assert "does not track job state" in capsys.readouterr().out


def test_reports_a_clear_error_when_procrastinate_is_configured_but_database_url_is_missing(
    tmp_path: Path, capsys, monkeypatch
):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    (tmp_path / "fymo.yml").write_text("jobs:\n  provider: procrastinate\n")

    with pytest.raises(SystemExit) as exc_info:
        run_jobs_status(tmp_path)

    assert exc_info.value.code == 1
    assert "DATABASE_URL" in capsys.readouterr().out


def test_prints_counts_and_recent_jobs_from_a_tracking_provider(tmp_path: Path, capsys):
    (tmp_path / "fymo.yml").write_text(
        "jobs:\n"
        "  provider:\n"
        "    class: tests.cli.test_jobs_status.StubTrackingProvider\n"
    )

    run_jobs_status(tmp_path)

    out = capsys.readouterr().out
    assert "stub-tracking" in out
    assert "todo" in out and "2" in out
    assert "succeeded" in out and "40" in out
    # Recent-jobs table: id, task name, status, queued-at all visible.
    assert "42" in out and "send_email" in out
    assert "2026-07-16 10:00:00" in out
    # A job with no queued-at timestamp renders a placeholder, not "None".
    assert "crunch" in out and "None" not in out


def test_passes_the_limit_through_to_the_provider(tmp_path: Path):
    (tmp_path / "fymo.yml").write_text(
        "jobs:\n"
        "  provider:\n"
        "    class: tests.cli.test_jobs_status.StubTrackingProvider\n"
    )

    run_jobs_status(tmp_path, limit=3)

    assert StubTrackingProvider.last_limit == 3


def test_degrades_gracefully_when_the_provider_only_reports_counts(tmp_path: Path, capsys):
    (tmp_path / "fymo.yml").write_text(
        "jobs:\n"
        "  provider:\n"
        "    class: tests.cli.test_jobs_status.StubCountsOnlyProvider\n"
    )

    run_jobs_status(tmp_path)

    out = capsys.readouterr().out
    assert "todo" in out
    assert "does not list individual jobs" in out


def test_closes_the_provider_when_done(tmp_path: Path):
    """A status read is a short-lived process, so the provider's database
    connection must be released explicitly, not left to interpreter
    shutdown (psycopg's pool complains loudly there on Python 3.14)."""
    (tmp_path / "fymo.yml").write_text(
        "jobs:\n"
        "  provider:\n"
        "    class: tests.cli.test_jobs_status.StubClosableProvider\n"
    )

    run_jobs_status(tmp_path)

    assert StubClosableProvider.closed


def test_dev_flag_sets_fymo_dev_and_loads_dotenv(tmp_path: Path, monkeypatch):
    """Same contract `fymo jobs-worker --dev` has (issue #44): DATABASE_URL
    usually lives in .env during dev, so jobs-status must be able to load
    it the same way. Proven the same way as test_jobs_worker.py: fymo.yml
    only parses if .env got loaded first."""
    monkeypatch.delenv("FYMO_TEST_STATUS_DEVFLAG", raising=False)
    monkeypatch.delenv("FYMO_DEV", raising=False)
    (tmp_path / ".env").write_text("FYMO_TEST_STATUS_DEVFLAG=loaded\n")
    (tmp_path / "fymo.yml").write_text("name: ${FYMO_TEST_STATUS_DEVFLAG}\n")

    # Default threaded provider => SystemExit(1), but only after fymo.yml
    # parsed, which requires the .env var to be present.
    with pytest.raises(SystemExit):
        run_jobs_status(tmp_path, dev=True)

    assert os.environ.get("FYMO_DEV") == "1"
    assert os.environ["FYMO_TEST_STATUS_DEVFLAG"] == "loaded"


def test_without_dev_flag_ignores_dotenv(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FYMO_TEST_STATUS_NOFLAG", raising=False)
    monkeypatch.delenv("FYMO_DEV", raising=False)
    (tmp_path / ".env").write_text("FYMO_TEST_STATUS_NOFLAG=should-not-load\n")

    with pytest.raises(SystemExit):
        run_jobs_status(tmp_path)

    assert "FYMO_TEST_STATUS_NOFLAG" not in os.environ
