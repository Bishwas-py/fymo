"""Discover app/jobs/*.py — the functions a JobProvider can submit by name.

Mirrors fymo.remote.discovery's directory-walking convention (skip
`_`-prefixed modules and functions, one importable package per project
root) without any of the remote-function machinery — job tasks are
invoked by the configured JobProvider, never directly by a browser
client, so there's no type-hint requirement, no codegen, no hashing.
"""
from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from typing import Callable, Dict


def _ensure_parent_packages(project_root: Path) -> None:
    """Ensure app and app.jobs packages are imported from project_root.

    Evicts stale sys.modules entries pointing at a different project root
    (the same fix fymo.remote.discovery already applies for app.remote),
    so a second project's app/jobs/*.py isn't shadowed by a previous one
    imported earlier in the same process.
    """
    for pkg in ("app", "app.jobs"):
        cached = sys.modules.get(pkg)
        if cached is not None:
            spec = getattr(cached, "__spec__", None)
            origin = getattr(spec, "origin", None) if spec else None
            if origin is None:
                del sys.modules[pkg]
            else:
                pkg_path = Path(origin).resolve()
                try:
                    pkg_path.relative_to(project_root.resolve())
                except ValueError:
                    del sys.modules[pkg]
        if pkg not in sys.modules:
            importlib.import_module(pkg)


def discover_job_tasks(project_root: Path) -> Dict[str, Callable]:
    """Return {function_name: callable} for every non-private top-level
    function in app/jobs/*.py. Returns {} if the directory doesn't exist —
    jobs are an optional feature, most apps won't have one.

    Self-contained: temporarily adds project_root to sys.path for the
    duration of the import (removing it again afterward) so `app.jobs.*`
    resolves regardless of whether a caller already did that dance for
    `app.remote.*` — unlike fymo.remote.discovery, which leaves this step
    to its caller (BuildPipeline), this function doesn't require callers
    to remember it.
    """
    project_root = Path(project_root)
    jobs_dir = project_root / "app" / "jobs"
    if not jobs_dir.is_dir():
        return {}

    project_root_str = str(project_root)
    added = project_root_str not in sys.path
    if added:
        sys.path.insert(0, project_root_str)
    try:
        _ensure_parent_packages(project_root)

        tasks: Dict[str, Callable] = {}
        for py in sorted(jobs_dir.glob("*.py")):
            if py.name == "__init__.py" or py.stem.startswith("_"):
                continue
            module_name = py.stem
            full = f"app.jobs.{module_name}"
            # Evict + fresh import, never importlib.reload: reload reuses
            # the module __dict__, so functions from a previously imported
            # version (e.g. another project root, or an edited file) would
            # leak into this discovery.
            if full in sys.modules:
                del sys.modules[full]
            mod = importlib.import_module(full)
            for name, obj in vars(mod).items():
                if name.startswith("_"):
                    continue
                if not inspect.isfunction(obj):
                    continue
                if getattr(obj, "__module__", None) != full:
                    continue
                tasks[name] = obj
        return tasks
    finally:
        if added and project_root_str in sys.path:
            sys.path.remove(project_root_str)
