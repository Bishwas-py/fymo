"""Minimal in-process background job runner.

fymo is a synchronous per-request WSGI framework — there is no built-in
async task queue. This module gives an app just enough to enqueue a
long-running callable (e.g. an AI agent driving a headless browser) from
inside a remote function and return immediately, instead of blocking the
request for the callable's full duration.

Deliberately NOT a FymoApp-managed subsystem: an app starts/uses this from
its own entry point (mirroring how the app decides to run a scheduler),
exactly the way you'd wire any other app-level background service. Job
state (progress, result, success/failure) is NOT tracked here either — the
submitted callable is expected to persist whatever state it needs (e.g. a
database row) itself; a poller then reads that external state. This module
only bounds concurrency and isolates failures so one bad job can't take
down the pool or the calling request.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("fymo.jobs")


class JobRunner:
    """A bounded-concurrency background executor.

    Intended to be used as a process-wide singleton per fymo worker process
    (see `get_shared_runner`/`set_shared_runner` below) — submitting into
    several independent JobRunners in the same process defeats the point of
    bounding concurrency.
    """

    def __init__(self, max_workers: int = 3):
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="fymo-job",
        )

    def submit(self, fn: Callable[..., None], *args, **kwargs) -> None:
        """Run `fn(*args, **kwargs)` on a bounded background thread.

        Any exception `fn` raises is logged and swallowed — it must not
        crash the executor or the calling request. The caller is responsible
        for recording success/failure itself (e.g. writing to a database
        row) before returning, since nothing here surfaces a return value or
        exception back to the submitter.
        """
        future = self._executor.submit(fn, *args, **kwargs)
        future.add_done_callback(self._log_if_failed)

    @staticmethod
    def _log_if_failed(future: Future) -> None:
        exc = future.exception()
        if exc is not None:
            logger.error("background job raised", exc_info=exc)

    def shutdown(self, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait)


_shared_runner: Optional[JobRunner] = None
_lock = threading.Lock()


def set_shared_runner(runner: JobRunner) -> None:
    """Replace the process-wide shared JobRunner (e.g. with a custom
    max_workers for production). Shuts down the previous shared runner
    first (non-blocking) so its worker threads don't leak."""
    global _shared_runner
    with _lock:
        if _shared_runner is not None and _shared_runner is not runner:
            _shared_runner.shutdown(wait=False)
        _shared_runner = runner


def get_shared_runner() -> JobRunner:
    """Return the process-wide shared JobRunner, creating a default
    (max_workers=3) one on first use."""
    global _shared_runner
    with _lock:
        if _shared_runner is None:
            _shared_runner = JobRunner()
        return _shared_runner


def reset_shared_runner() -> None:
    """Test-only: shut down and clear the shared runner so each test gets
    isolation. Not meant to be called from application code."""
    global _shared_runner
    with _lock:
        if _shared_runner is not None:
            _shared_runner.shutdown(wait=False)
        _shared_runner = None


# --- JobProvider singleton ---------------------------------------------
#
# The pluggable seam (fymo.jobs.providers.JobProvider) that sits above
# JobRunner: unlike JobRunner, a FymoApp wires this up automatically at
# startup (see FymoApp._init_jobs in fymo.core.server), the same way it
# wires up auth. An app never constructs a provider itself — it calls
# `get_job_provider().submit(...)` from a remote function and lets the
# process-wide provider (built from fymo.yml's `jobs:` section, defaulting
# to ThreadedJobProvider) route the call.

_job_provider: Optional[Any] = None
_provider_lock = threading.Lock()


def set_job_provider(provider: Any) -> None:
    """Replace the process-wide JobProvider singleton."""
    global _job_provider
    with _provider_lock:
        _job_provider = provider


def get_job_provider() -> Any:
    """Return the process-wide JobProvider, creating a default
    (unconfigured ThreadedJobProvider, no registered tasks) on first use.

    A provider reached this way outside of `init_job_provider`/FymoApp
    startup has no tasks registered — submit() will raise "unknown job
    task" for everything. Real apps get a populated provider because
    FymoApp calls `init_job_provider` during __init__.
    """
    global _job_provider
    with _provider_lock:
        if _job_provider is None:
            from fymo.jobs.providers.threaded import ThreadedJobProvider
            _job_provider = ThreadedJobProvider()
        return _job_provider


def init_job_provider(project_root: Path, provider_config: Any) -> Any:
    """Build the configured JobProvider, register every app/jobs/*.py task
    with it, install it as the process-wide singleton, and return it.

    Called once by FymoApp at startup (mirrors auth's `_init_auth`):
    `provider_config` is `ConfigManager.get_jobs_config().get("provider")`.
    """
    from fymo.jobs.discovery import discover_job_tasks
    from fymo.jobs.providers.registry import build_job_provider

    tasks = discover_job_tasks(project_root)
    provider = build_job_provider(provider_config)
    provider.register_tasks(tasks)
    set_job_provider(provider)
    return provider


def reset_job_provider() -> None:
    """Test-only: clear the shared JobProvider so each test gets isolation.
    Not meant to be called from application code."""
    global _job_provider
    with _provider_lock:
        _job_provider = None
