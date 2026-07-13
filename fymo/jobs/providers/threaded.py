"""ThreadedJobProvider — wraps the existing in-process fymo.jobs.JobRunner.

No external dependency, no separate worker process: the simplest possible
provider, and the fallback default for a project that hasn't configured
`jobs.provider` in fymo.yml — same role `password` plays for auth. Same
durability trade-off `fymo.jobs` always had: a job dies if the process
restarts mid-run. Use `ProcrastinateJobProvider` for anything that needs
to survive a restart or scale independently of the web tier.
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
        get_shared_runner().submit(self._tasks[task_name], *args, **kwargs)
