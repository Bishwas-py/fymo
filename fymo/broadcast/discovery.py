"""Discover app/broadcasts/*.py — the channels publish()/subscribe know.

Same directory-walking convention as fymo.jobs.discovery (skip `_`-prefixed
modules and functions, per-project-root module cache eviction). Channel
names must be globally unique across modules: publish() addresses a channel
by bare name ("run_status", not "runs.run_status"), so a collision is a
loud startup error instead of a silent wrong-channel publish.
"""
from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from typing import Callable, Dict, Tuple


class DuplicateChannelError(Exception):
    """Two app/broadcasts modules declare the same channel name."""


def _ensure_parent_packages(project_root: Path) -> None:
    for pkg in ("app", "app.broadcasts"):
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


def discover_broadcast_channels(project_root: Path) -> Dict[str, Tuple[str, Callable]]:
    """Return {channel_name: (module_name, channel_fn)} for every
    non-private top-level function in app/broadcasts/*.py. Returns {} when
    the directory doesn't exist — broadcasts are optional."""
    project_root = Path(project_root)
    broadcasts_dir = project_root / "app" / "broadcasts"
    if not broadcasts_dir.is_dir():
        return {}

    project_root_str = str(project_root)
    added = project_root_str not in sys.path
    if added:
        sys.path.insert(0, project_root_str)
    try:
        _ensure_parent_packages(project_root)

        channels: Dict[str, Tuple[str, Callable]] = {}
        for py in sorted(broadcasts_dir.glob("*.py")):
            if py.name == "__init__.py" or py.stem.startswith("_"):
                continue
            module_name = py.stem
            full = f"app.broadcasts.{module_name}"
            # Evict + fresh import, never importlib.reload: reload reuses
            # the module __dict__, so channels from a previously imported
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
                if name in channels:
                    raise DuplicateChannelError(
                        f"broadcast channel {name!r} is declared in both "
                        f"app/broadcasts/{channels[name][0]}.py and "
                        f"app/broadcasts/{module_name}.py — channel names "
                        "must be unique across modules"
                    )
                channels[name] = (module_name, obj)
        return channels
    finally:
        if added and project_root_str in sys.path:
            sys.path.remove(project_root_str)
