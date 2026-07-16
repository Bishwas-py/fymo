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
  * job_counts()     - read-only status surface: how many jobs the
    provider's own bookkeeping holds per status (e.g. todo/doing/failed).
    Returns None when the provider doesn't track job state at all (the
    inert default), as distinct from an empty dict, which means "tracked,
    and there are no jobs". Backs the `fymo jobs-status` CLI command.
  * list_recent_jobs() - the other half of the status surface: the newest
    jobs as JobRecord rows, newest first. None again means "not tracked";
    a provider may implement job_counts() without this and the CLI
    degrades gracefully.
  * close()          - release any connections the provider holds. Inert
    by default; matters for short-lived processes (`fymo jobs-status`)
    where a pooled connection torn down at interpreter shutdown is noisy.
    A closed provider must reconnect transparently on the next call.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from fymo.core.schema import SchemaObject


@dataclass(frozen=True)
class JobRecord:
    """One job as reported by a provider's status surface. `id` is a string
    because it's provider-native (procrastinate's bigserial, a UUID, ...);
    `queued_at` is None when the provider doesn't record enqueue time."""

    id: str
    task_name: str
    status: str
    queued_at: Optional[datetime]


@runtime_checkable
class JobProvider(Protocol):
    id: str

    def register_tasks(self, tasks: Dict[str, Callable]) -> None: ...
    def submit(self, task_name: str, *args, **kwargs) -> None: ...
    def run_worker(self) -> None: ...
    def job_counts(self) -> Optional[Dict[str, int]]: ...
    def list_recent_jobs(self, limit: int = 10) -> Optional[List[JobRecord]]: ...
    def close(self) -> None: ...


class BaseJobProvider:
    """Inert defaults so a provider only implements what it needs."""

    id: str = ""

    def register_tasks(self, tasks: Dict[str, Callable]) -> None:
        pass

    def owned_schema_objects(self) -> Tuple[SchemaObject, ...]:
        """The database objects this provider creates for itself, so schema
        diff tooling can be told to leave them alone (`fymo schema
        provider-tables`). Deliberately not part of the JobProvider
        Protocol: it's runtime-checkable, and requiring the method would
        break isinstance() for custom providers that predate the seam.
        Providers that create nothing declare nothing."""
        return ()

    def submit(self, task_name: str, *args, **kwargs) -> None:
        raise NotImplementedError

    def run_worker(self) -> None:
        raise RuntimeError(
            f"{self.id!r} job provider has no separate worker process — "
            "only providers backed by a durable queue (e.g. 'procrastinate') "
            "support `fymo jobs-worker`"
        )

    def job_counts(self) -> Optional[Dict[str, int]]:
        """None: this provider doesn't track job state (see module docstring)."""
        return None

    def list_recent_jobs(self, limit: int = 10) -> Optional[List[JobRecord]]:
        """None: this provider doesn't track job state (see module docstring)."""
        return None

    def close(self) -> None:
        """Nothing held by default (see module docstring)."""
        pass
