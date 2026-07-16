"""ProcrastinateJobProvider — Postgres-native task queue as a JobProvider.

Durable and horizontally scalable: a submitted job survives a web-process
restart and is picked up by a separate `fymo jobs-worker` process (or
several), unlike ThreadedJobProvider's in-process fire-and-forget. Needs a
real Postgres database — reusing the app's own database is fine,
Procrastinate keeps its state in its own tables (`procrastinate_jobs`, etc).
"""
from __future__ import annotations

import inspect
import logging
import os
from typing import Callable, Dict, List

from fymo.jobs.providers.base import BaseJobProvider, JobRecord

_DEFAULT_ENV_VAR = "DATABASE_URL"

# The statuses procrastinate's list_queues() aggregates report (its
# 'aborting' enum value is legacy, unused since procrastinate 3.0).
_STATUSES = ("todo", "doing", "succeeded", "failed", "cancelled", "aborted")

# list_recent_jobs() can't come from procrastinate's public JobManager API:
# list_jobs() has no LIMIT (it fetches the whole table, which delete_old_jobs
# may never have pruned) and its Job model carries no enqueue timestamp.
# Both live in procrastinate's documented schema instead: the jobs row plus
# its 'deferred' event (procrastinate_events records every transition; the
# insert trigger writes 'deferred' when a job is first queued).
_RECENT_JOBS_QUERY = """
SELECT j.id,
       j.task_name,
       j.status,
       (SELECT MIN(e.at) FROM procrastinate_events e
         WHERE e.job_id = j.id AND e.type = 'deferred') AS queued_at
  FROM procrastinate_jobs j
 ORDER BY j.id DESC
 LIMIT %(limit)s
"""


class DropProcrastinateJobErrorRecord(logging.Filter):
    """Drop procrastinate's permanent-failure outcome record.

    procrastinate's worker logs ``Job {call_string} ended with status:
    Error`` at ERROR when a job permanently fails (retries exhausted) --
    ``call_string`` renders every job kwarg value, so this record leaks
    job arguments even past the WARNING level cap run_worker() applies to
    the "procrastinate" logger (ERROR >= WARNING). It also duplicates
    fymo's own ``job failed`` ERROR line, which already carries the job
    name, status, duration, and traceback without the arguments.

    The record is identified by the ``action == "job_error"`` extra that
    procrastinate's Worker._log_job_outcome attaches; the other outcome
    actions (job_success, job_aborted, job_aborted_retry, job_error_retry)
    are INFO-only, so the level cap already handles them by default and
    they stay available to an app that explicitly opts into INFO.

    This filter must be attached to "procrastinate.worker" -- the record's
    ORIGIN logger (worker.py's module-level ``logging.getLogger(__name__)``)
    -- because stdlib logger-level filters only run on the logger a record
    is logged through, never on ancestors, so attaching it to the
    "procrastinate" parent would do nothing.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "action", None) != "job_error"


def _import_procrastinate():
    """Import procrastinate with an actionable error — it's an optional
    dependency, so `jobs: provider: procrastinate` without the extra
    installed must say how to fix it, not dump a ModuleNotFoundError."""
    try:
        import procrastinate
    except ImportError as e:
        raise RuntimeError(
            "the 'procrastinate' job provider needs the procrastinate "
            "package — install it with: pip install 'fymo[procrastinate]'"
        ) from e
    return procrastinate


class ProcrastinateJobProvider(BaseJobProvider):
    id = "procrastinate"

    def __init__(self, database_url_env: str = _DEFAULT_ENV_VAR) -> None:
        self._database_url_env = database_url_env
        self._tasks: Dict[str, Callable] = {}
        self._app = None  # lazy; rebuilt whenever tasks are (re-)registered

    def register_tasks(self, tasks: Dict[str, Callable]) -> None:
        self._tasks = dict(tasks)
        self._app = None  # invalidate cached app so it picks up the new set

    def submit(self, task_name: str, *args, **kwargs) -> None:
        if task_name not in self._tasks:
            raise ValueError(f"unknown job task: {task_name!r}")
        bound = inspect.signature(self._tasks[task_name]).bind(*args, **kwargs)
        bound.apply_defaults()
        self._get_app().configure_task(name=task_name).defer(**bound.arguments)

    def run_worker(self, **kwargs) -> None:
        """Block, actually executing submitted jobs — the `fymo jobs-worker`
        entry point. Runs in its own OS process, separate from the web
        server, so it needs its own App with an async-capable connector
        (`PsycopgConnector`) — unlike `submit()`'s `_get_app()`, which uses
        the sync connector deferring needs. Defaults (`wait=True,
        listen_notify=True`) mean this call never returns under normal
        operation; pass `wait=False` (e.g. in a test) to drain whatever's
        queued and return instead.
        """
        conninfo = self._database_url()  # config check before import: the
        # cheaper, more common misconfiguration reports first
        procrastinate = _import_procrastinate()

        connector = procrastinate.PsycopgConnector(conninfo=conninfo)
        app = procrastinate.App(connector=connector)
        from fymo.jobs.lifecycle import run_with_lifecycle
        import functools

        for name, fn in self._tasks.items():
            # Wrap execution with lifecycle logging. reraise=True: the
            # exception must propagate so procrastinate marks the job
            # failed / applies its retry policy. functools.wraps preserves
            # the original signature for procrastinate's introspection.
            def _make(wrapped_name: str, wrapped_fn: Callable) -> Callable:
                @functools.wraps(wrapped_fn)
                def _run(*args, **kwargs):
                    return run_with_lifecycle(
                        wrapped_name, wrapped_fn, args, kwargs, reraise=True,
                    )
                return _run

            app.task(name=name)(_make(name, fn))

        # procrastinate's own INFO lines include job.call_string, which
        # renders every job kwarg value (worker.py "Starting job ...") --
        # letting that through fymo's root-logger handler would leak job
        # arguments into the log stream, violating fymo's PII rule (job
        # arguments are never logged; fymo's own lifecycle lines carry
        # name/status/duration only). Cap procrastinate to WARNING by
        # default so errors still surface; an app that accepts the
        # trade-off can explicitly setLevel(logging.INFO) on the
        # "procrastinate" logger after startup, which this deliberately
        # respects by only acting when the level is unset.
        procrastinate_logger = logging.getLogger("procrastinate")
        if procrastinate_logger.level == logging.NOTSET:
            procrastinate_logger.setLevel(logging.WARNING)

        # The level cap can't stop the one argument-echoing record emitted
        # at ERROR (permanent job failure) -- drop it at its origin logger.
        # See DropProcrastinateJobErrorRecord. Guarded so repeated
        # run_worker() calls don't stack duplicate filters.
        worker_logger = logging.getLogger("procrastinate.worker")
        if not any(
            isinstance(f, DropProcrastinateJobErrorRecord)
            for f in worker_logger.filters
        ):
            worker_logger.addFilter(DropProcrastinateJobErrorRecord())

        app.run_worker(**kwargs)

    def job_counts(self) -> Dict[str, int]:
        """Sum procrastinate's own per-queue status aggregates (public
        JobManager.list_queues() API) into one counts-by-status dict."""
        counts = dict.fromkeys(_STATUSES, 0)
        for queue_stats in self._get_app().job_manager.list_queues():
            for status in _STATUSES:
                counts[status] += queue_stats[status]
        return counts

    def list_recent_jobs(self, limit: int = 10) -> List[JobRecord]:
        """Newest jobs first, straight from procrastinate's job table (see
        _RECENT_JOBS_QUERY for why this bypasses the public API), through
        the same opened sync connector submit() uses."""
        rows = self._get_app().connector.execute_query_all(
            _RECENT_JOBS_QUERY, limit=limit,
        )
        return [
            JobRecord(
                id=str(row["id"]),
                task_name=row["task_name"],
                status=row["status"],
                queued_at=row["queued_at"],
            )
            for row in rows
        ]

    def close(self) -> None:
        """Close the cached sync app's connector and drop the cache so the
        next call reconnects. Matters for short-lived processes (`fymo
        jobs-status`): psycopg's pool complains loudly when it's left to be
        torn down by interpreter shutdown instead of closed explicitly."""
        if self._app is not None:
            self._app.close()
            self._app = None

    def _get_app(self):
        if self._app is None:
            conninfo = self._database_url()
            procrastinate = _import_procrastinate()

            connector = procrastinate.SyncPsycopgConnector(conninfo=conninfo)
            app = procrastinate.App(connector=connector)
            for name, fn in self._tasks.items():
                app.task(name=name)(fn)
            app.open()
            self._app = app
        return self._app

    def _database_url(self) -> str:
        url = os.environ.get(self._database_url_env)
        if not url:
            raise RuntimeError(
                f"ProcrastinateJobProvider needs ${self._database_url_env} set "
                "to a Postgres connection string"
            )
        return url
