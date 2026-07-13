"""Tests for fymo.jobs — the bounded-concurrency background job runner."""
import threading
import time

import pytest

from fymo.jobs import JobRunner, get_shared_runner, reset_shared_runner, set_shared_runner


@pytest.fixture(autouse=True)
def _reset_shared_runner():
    """Isolate the process-wide shared runner between tests."""
    reset_shared_runner()
    yield
    reset_shared_runner()


def test_submit_runs_the_callable():
    runner = JobRunner(max_workers=2)
    done = threading.Event()
    result = {}

    def job(x, y):
        result["sum"] = x + y
        done.set()

    runner.submit(job, 2, 3)
    assert done.wait(timeout=2), "job did not run within 2s"
    assert result["sum"] == 5
    runner.shutdown(wait=True)


def test_submit_swallows_exceptions_and_keeps_runner_alive():
    runner = JobRunner(max_workers=2)
    done = threading.Event()

    def failing_job():
        raise ValueError("boom")

    def healthy_job():
        done.set()

    runner.submit(failing_job)
    runner.submit(healthy_job)
    assert done.wait(timeout=2), "runner did not process the job after a prior failure"
    runner.shutdown(wait=True)


def test_max_workers_bounds_concurrency():
    runner = JobRunner(max_workers=2)
    lock = threading.Lock()
    current = {"n": 0}
    max_seen = {"n": 0}

    def job():
        with lock:
            current["n"] += 1
            max_seen["n"] = max(max_seen["n"], current["n"])
        time.sleep(0.2)
        with lock:
            current["n"] -= 1

    for _ in range(4):
        runner.submit(job)

    time.sleep(0.5)  # let the first wave overlap and the pool cycle to the second
    runner.shutdown(wait=True)
    assert max_seen["n"] <= 2, f"expected at most 2 concurrent jobs, saw {max_seen['n']}"


def test_shared_runner_is_a_process_wide_singleton_by_default():
    a = get_shared_runner()
    b = get_shared_runner()
    assert a is b
    a.shutdown(wait=False)


def test_set_shared_runner_overrides_the_default():
    custom = JobRunner(max_workers=1)
    set_shared_runner(custom)
    assert get_shared_runner() is custom
    custom.shutdown(wait=False)


def test_set_shared_runner_shuts_down_the_previous_runner():
    first = JobRunner(max_workers=1)
    set_shared_runner(first)
    assert get_shared_runner() is first

    second = JobRunner(max_workers=1)
    set_shared_runner(second)
    assert get_shared_runner() is second

    # The previous runner's executor must be shut down (non-blocking) so its
    # worker threads don't leak — submitting to it now should be rejected
    # rather than silently accepted by an orphaned thread pool.
    with pytest.raises(RuntimeError):
        first.submit(lambda: None)

    second.shutdown(wait=False)
