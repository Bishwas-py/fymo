"""Discover route entries from app/templates/."""
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class Route:
    """A route entry corresponds to one app/templates/<name>/index.svelte."""
    name: str
    entry_path: Path  # absolute path to index.svelte


def discover_routes(templates_dir: Path) -> List[Route]:
    """Return one Route per <templates_dir>/<name>/index.svelte."""
    if not templates_dir.is_dir():
        return []
    routes: List[Route] = []
    for child in sorted(templates_dir.iterdir()):
        if not child.is_dir():
            continue
        entry = child / "index.svelte"
        if entry.is_file():
            routes.append(Route(name=child.name, entry_path=entry.resolve()))
    return routes
