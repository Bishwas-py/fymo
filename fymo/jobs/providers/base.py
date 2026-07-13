"""The JobProvider seam — mirrors fymo.auth.providers.AuthProvider exactly.

A provider contributes only the surface it needs. The framework never
branches on provider *type*, it just calls the two hooks:

  * register_tasks() — called once at app init with every discovered
    app/jobs/*.py function, keyed by name. A provider uses this to wire
    each function into its own underlying task-registration mechanism.
  * submit()         — enqueue task_name(*args, **kwargs) to run in the
    background. Fire-and-forget from the caller's perspective: no return
    value, no blocking. The task itself is responsible for persisting its
    own outcome (e.g. writing to a database row) — the same contract
    fymo.jobs.JobRunner already had before providers existed.
  * run_worker()     — block forever, actually executing submitted jobs.
    Only meaningful for providers with a separate worker process (e.g.
    Procrastinate); in-process providers like ThreadedJobProvider have
    nothing to run here since submit() already does the work. Backs the
    `fymo jobs-worker` CLI command.
"""
from __future__ import annotations

from typing import Callable, Dict, Protocol, runtime_checkable


@runtime_checkable
class JobProvider(Protocol):
    id: str

    def register_tasks(self, tasks: Dict[str, Callable]) -> None: ...
    def submit(self, task_name: str, *args, **kwargs) -> None: ...
    def run_worker(self) -> None: ...


class BaseJobProvider:
    """Inert defaults so a provider only implements what it needs."""

    id: str = ""

    def register_tasks(self, tasks: Dict[str, Callable]) -> None:
        pass

    def submit(self, task_name: str, *args, **kwargs) -> None:
        raise NotImplementedError

    def run_worker(self) -> None:
        raise RuntimeError(
            f"{self.id!r} job provider has no separate worker process — "
            "only providers backed by a durable queue (e.g. 'procrastinate') "
            "support `fymo jobs-worker`"
        )
