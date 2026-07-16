"""Tests for ThreadedJobProvider — the in-process, no-external-deps provider."""
import threading

import pytest

from fymo.jobs import reset_shared_runner
from fymo.jobs.providers.threaded import ThreadedJobProvider


@pytest.fixture(autouse=True)
def _reset():
    reset_shared_runner()
    yield
    reset_shared_runner()


def test_submit_runs_a_registered_task():
    provider = ThreadedJobProvider()
    done = threading.Event()
    result = {}

    def do_work(x, y):
        result["sum"] = x + y
        done.set()

    provider.register_tasks({"do_work": do_work})
    provider.submit("do_work", 2, 3)
    assert done.wait(timeout=2)
    assert result["sum"] == 5


def test_submit_raises_on_unknown_task():
    provider = ThreadedJobProvider()
    provider.register_tasks({})
    with pytest.raises(ValueError, match="unknown job task: 'nope'"):
        provider.submit("nope")


def test_id_is_threaded():
    assert ThreadedJobProvider().id == "threaded"


def test_job_counts_returns_none():
    """Deliberate: the executor's state lives inside the web process, and
    `fymo jobs-status` runs as its own OS process, so a fresh provider
    there would always report zeros, worse than saying "not tracked"."""
    assert ThreadedJobProvider().job_counts() is None


def test_list_recent_jobs_returns_none():
    assert ThreadedJobProvider().list_recent_jobs() is None
