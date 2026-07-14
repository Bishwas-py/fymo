"""Generic app/<subpackage>/*.py top-level function discovery.

fymo.jobs.discovery and fymo.broadcast.discovery were structural copies
(same sys.path dance, same stale-module eviction, same walk) that had
already diverged on collision policy: broadcasts raised on a duplicate
channel name, jobs silently let the last module win. The shared walker
makes collision handling a required argument, so the two can't disagree
by accident again.
"""
from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from typing import Callable, Dict, Tuple


def _ensure_parent_packages(project_root: Path, subpackage: str) -> None:
    for pkg in ("app", f"app.{subpackage}"):
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


def discover_app_functions(
    project_root: Path,
    subpackage: str,
    on_duplicate: Callable[[str, str, str], Exception],
) -> Dict[str, Tuple[str, Callable]]:
    """Return {name: (module_stem, fn)} for every non-private top-level
    function defined (not merely imported) in app/<subpackage>/*.py.
    Returns {} when the directory doesn't exist. Raises
    on_duplicate(name, first_module, second_module) when two modules
    define the same function name -- collision policy is the caller's,
    but HAVING one is not optional."""
    project_root = Path(project_root)
    pkg_dir = project_root / "app" / subpackage
    if not pkg_dir.is_dir():
        return {}

    project_root_str = str(project_root)
    added = project_root_str not in sys.path
    if added:
        sys.path.insert(0, project_root_str)
    try:
        _ensure_parent_packages(project_root, subpackage)

        found: Dict[str, Tuple[str, Callable]] = {}
        for py in sorted(pkg_dir.glob("*.py")):
            if py.name == "__init__.py" or py.stem.startswith("_"):
                continue
            module_name = py.stem
            full = f"app.{subpackage}.{module_name}"
            # Evict + fresh import, never importlib.reload: reload reuses
            # the module __dict__, so functions from a previously imported
            # version would leak into this discovery.
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
                if name in found:
                    raise on_duplicate(name, found[name][0], module_name)
                found[name] = (module_name, obj)
        return found
    finally:
        if added and project_root_str in sys.path:
            sys.path.remove(project_root_str)
