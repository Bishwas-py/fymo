"""ProcrastinateJobProvider — Postgres-native task queue as a JobProvider.

Durable and horizontally scalable: a submitted job survives a web-process
restart and is picked up by a separate `fymo jobs-worker` process (or
several), unlike ThreadedJobProvider's in-process fire-and-forget. Needs a
real Postgres database — reusing the app's own database is fine,
Procrastinate keeps its state in its own tables (`procrastinate_jobs`, etc).
"""
from __future__ import annotations

import inspect
import os
from typing import Callable, Dict

from fymo.jobs.providers.base import BaseJobProvider

_DEFAULT_ENV_VAR = "DATABASE_URL"


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
        for name, fn in self._tasks.items():
            app.task(name=name)(fn)
        app.run_worker(**kwargs)

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
