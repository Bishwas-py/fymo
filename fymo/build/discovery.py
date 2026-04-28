"""Discover route entries from app/templates/."""
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class Route:
    """A route entry corresponds to one app/templates/<name>/index.svelte or show.svelte."""
    name: str
    entry_path: Path  # absolute path to the entry svelte file


def discover_routes(templates_dir: Path) -> List[Route]:
    """Return one Route per <templates_dir>/<name>/index.svelte or <name>/show.svelte.

    Directories whose names start with ``_`` (e.g. ``_shared``) are skipped
    because they contain shared components rather than routable pages.

    ``index.svelte`` takes precedence over ``show.svelte`` so that the root
    index route is not accidentally overridden.
    """
    if not templates_dir.is_dir():
        return []
    routes: List[Route] = []
    for child in sorted(templates_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("_"):
            continue
        for candidate in ("index.svelte", "show.svelte"):
            entry = child / candidate
            if entry.is_file():
                routes.append(Route(name=child.name, entry_path=entry.resolve()))
                break
    return routes
