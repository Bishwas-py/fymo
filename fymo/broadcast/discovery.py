"""Discover app/broadcasts/*.py — the channels publish()/subscribe know.

Same directory-walking convention as fymo.jobs.discovery (skip `_`-prefixed
modules and functions, per-project-root module cache eviction). Channel
names must be globally unique across modules: publish() addresses a channel
by bare name ("run_status", not "runs.run_status"), so a collision is a
loud startup error instead of a silent wrong-channel publish.

Thin wrapper over fymo.core.app_discovery's shared walker.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Tuple

from fymo.core.app_discovery import discover_app_functions


class DuplicateChannelError(Exception):
    """Two app/broadcasts modules declare the same channel name."""


def _on_duplicate(name: str, first_module: str, second_module: str) -> DuplicateChannelError:
    return DuplicateChannelError(
        f"broadcast channel {name!r} is declared in both "
        f"app/broadcasts/{first_module}.py and "
        f"app/broadcasts/{second_module}.py — channel names "
        "must be unique across modules"
    )


def discover_broadcast_channels(project_root: Path) -> Dict[str, Tuple[str, Callable]]:
    """Return {channel_name: (module_name, channel_fn)} for every
    non-private top-level function in app/broadcasts/*.py. Returns {} when
    the directory doesn't exist — broadcasts are optional."""
    return discover_app_functions(project_root, "broadcasts", _on_duplicate)
