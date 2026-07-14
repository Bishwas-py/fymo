"""Explicit marker for app/jobs/*.py task entry points.

Mirrors fymo.remote.decorators.remote: every non-underscore top-level
function in app/jobs/*.py already becomes a submittable task (see
fymo.jobs.discovery), so there's no opt-in/opt-out mode here the way
`remote.explicit_optin` gives app/remote/*.py, @task changes nothing about
what gets discovered. It exists so a developer can say "this is a real task
entry point" out loud, which is what makes discover_job_tasks's deprecation
warning for undecorated functions actionable instead of just noise.
"""
from typing import Callable, TypeVar

F = TypeVar("F", bound=Callable)


def task(fn: F) -> F:
    """Mark a function as an explicit background job task.

    Returns the function unchanged (no wrapping), it only stamps
    `__fymo_task__ = True` so discover_job_tasks can tell an intentional
    task entry point from a bare function that happens to be public and
    top-level. An undecorated function is still discovered and registered
    identically (backward compat); the marker only silences the
    deprecation-style warning discover_job_tasks logs for undecorated ones.
    """
    fn.__fymo_task__ = True
    return fn
