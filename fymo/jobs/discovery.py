"""Discover app/jobs/*.py — the functions a JobProvider can submit by name.

Mirrors fymo.remote.discovery's directory-walking convention (skip
`_`-prefixed modules and functions, one importable package per project
root) without any of the remote-function machinery — job tasks are
invoked by the configured JobProvider, never directly by a browser
client, so there's no type-hint requirement, no codegen, no hashing.

Thin wrapper over fymo.core.app_discovery's shared walker; task names
must be unique across modules, same as broadcast channel names.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Dict

from fymo.core.app_discovery import discover_app_functions

logger = logging.getLogger("fymo.jobs")


class DuplicateTaskError(Exception):
    """Two app/jobs modules define the same task name."""


def _on_duplicate(name: str, first_module: str, second_module: str) -> DuplicateTaskError:
    return DuplicateTaskError(
        f"job task {name!r} is declared in both "
        f"app/jobs/{first_module}.py and "
        f"app/jobs/{second_module}.py — task names "
        "must be unique across modules"
    )


def discover_job_tasks(project_root: Path) -> Dict[str, Callable]:
    """Return {function_name: callable} for every non-private top-level
    function in app/jobs/*.py. Returns {} if the directory doesn't exist —
    jobs are an optional feature, most apps won't have one. Raises
    DuplicateTaskError if two modules define the same task name.

    Self-contained: temporarily adds project_root to sys.path for the
    duration of the import (removing it again afterward) so `app.jobs.*`
    resolves regardless of whether a caller already did that dance for
    `app.remote.*` — unlike fymo.remote.discovery, which leaves this step
    to its caller (BuildPipeline), this function doesn't require callers
    to remember it.

    A function without the `@task` marker (fymo.jobs.task) is still
    registered exactly as before. This is intentionally not a breaking
    change, every existing app/jobs module keeps working unmodified, but it
    logs a one-line warning suggesting `@task` be added, since an
    undecorated top-level function becoming submittable is easy to do by
    accident in a module meant to stay a thin task registry.
    """
    found = discover_app_functions(project_root, "jobs", _on_duplicate)
    tasks: Dict[str, Callable] = {}
    for name, (module_stem, fn) in found.items():
        if not getattr(fn, "__fymo_task__", False):
            logger.warning(
                "app/jobs/%s.py: %r has no @task marker (fymo.jobs.task); "
                "it is still registered as a task for backward compatibility, "
                "but consider adding @task to make it explicit",
                module_stem, name,
            )
        tasks[name] = fn
    return tasks
