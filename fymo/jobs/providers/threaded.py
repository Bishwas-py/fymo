"""ThreadedJobProvider — wraps the existing in-process fymo.jobs.JobRunner.

No external dependency, no separate worker process: the simplest possible
provider, and the fallback default for a project that hasn't configured
`jobs.provider` in fymo.yml — same role `password` plays for auth. Same
durability trade-off `fymo.jobs` always had: a job dies if the process
restarts mid-run. Use `ProcrastinateJobProvider` for anything that needs
to survive a restart or scale independently of the web tier.

Deliberately keeps the base's None for job_counts()/list_recent_jobs()
(i.e. "job state is not tracked"): the executor's state lives inside the
web process, and `fymo jobs-status` runs as its own OS process, so the
fresh provider it builds could only ever report zeros. None makes the
CLI say "not tracked" instead, which is the honest answer. Apps that
need visibility into threaded jobs should follow the app-level progress
convention (docs/conventions.md) or switch to a durable provider.
"""
from __future__ import annotations

from typing import Callable, Dict

from fymo.jobs import get_shared_runner
from fymo.jobs.providers.base import BaseJobProvider


class ThreadedJobProvider(BaseJobProvider):
    id = "threaded"

    def __init__(self) -> None:
        self._tasks: Dict[str, Callable] = {}

    def register_tasks(self, tasks: Dict[str, Callable]) -> None:
        self._tasks = dict(tasks)

    def submit(self, task_name: str, *args, **kwargs) -> None:
        if task_name not in self._tasks:
            raise ValueError(f"unknown job task: {task_name!r}")
        from fymo.jobs.lifecycle import run_with_lifecycle
        # reraise=False: lifecycle logging owns the failure line; letting it
        # propagate would make JobRunner._log_if_failed log the same failure
        # a second time (and JobRunner's contract swallows it anyway).
        get_shared_runner().submit(
            run_with_lifecycle, task_name, self._tasks[task_name],
            args, kwargs, False,
        )
