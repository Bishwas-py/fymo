"""Shared per-job lifecycle logging wrapper.

Both JobProviders route actual task execution through run_with_lifecycle so
the jobs worker (and the in-process threaded runner) emit one line per job
at started/succeeded/failed with duration — mirroring the web tier's
access log. Job arguments are deliberately never logged (PII rule, see
fymo.core.logging.job_log).
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

from fymo.core.logging import job_log


def run_with_lifecycle(
    task_name: str,
    fn: Callable[..., Any],
    args: tuple = (),
    kwargs: Optional[dict] = None,
    reraise: bool = True,
) -> Any:
    """Execute fn(*args, **kwargs) with lifecycle logging.

    reraise=True (procrastinate): the exception propagates so the queue
    can mark the job failed / retry it. reraise=False (threaded): the
    exception is logged and swallowed — JobRunner's contract is that a
    failed job never crashes the pool, and swallowing here also prevents
    JobRunner._log_if_failed from double-logging the same failure.

    args/kwargs are explicit parameters (not *args/**kwargs) so a job
    whose own kwargs include e.g. `reraise` can never collide with this
    wrapper's options.
    """
    kwargs = kwargs or {}
    job_log(task_name, "started")
    start = time.perf_counter()
    try:
        result = fn(*args, **kwargs)
    except BaseException as exc:
        job_log(task_name, "failed", (time.perf_counter() - start) * 1000.0, exc_info=exc)
        if reraise:
            raise
        return None
    job_log(task_name, "succeeded", (time.perf_counter() - start) * 1000.0)
    return result
