"""Discover route entries and layouts from app/templates/."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class LayoutRef:
    """One _layout.svelte, optionally paired with a same-named _layout.py controller."""
    level: str                          # "root" | "resource"
    id: str                             # "_root" for root, else the resource dir name
    svelte_path: Path                   # absolute
    controller_module: Optional[str]    # dotted module path, or None if no controller file


@dataclass(frozen=True)
class Route:
    """A route entry corresponds to one app/templates/<name>/index.svelte or show.svelte."""
    name: str
    entry_path: Path  # absolute path to the entry svelte file
    layout_chain: List[LayoutRef] = field(default_factory=list)  # root before resource


def _controller_module_for(project_root: Path, *parts: str) -> Optional[str]:
    """Return the dotted module path for app/controllers/<parts>/_layout.py if it
    exists on disk, else None. `parts` is empty for the root layout."""
    py_path = project_root.joinpath("app", "controllers", *parts, "_layout.py")
    if not py_path.is_file():
        return None
    dotted = ["app", "controllers", *parts, "_layout"]
    return ".".join(dotted)


def _root_layout(templates_dir: Path, project_root: Path) -> Optional[LayoutRef]:
    svelte_path = templates_dir / "_layout.svelte"
    if not svelte_path.is_file():
        return None
    return LayoutRef(
        level="root",
        id="_root",
        svelte_path=svelte_path.resolve(),
        controller_module=_controller_module_for(project_root),
    )


def _resource_layout(templates_dir: Path, project_root: Path, resource: str) -> Optional[LayoutRef]:
    svelte_path = templates_dir / resource / "_layout.svelte"
    if not svelte_path.is_file():
        return None
    return LayoutRef(
        level="resource",
        id=resource,
        svelte_path=svelte_path.resolve(),
        controller_module=_controller_module_for(project_root, resource),
    )


def discover_routes(templates_dir: Path) -> List[Route]:
    """Return one Route per <templates_dir>/<name>/index.svelte or <name>/show.svelte.

    Directories whose names start with ``_`` are skipped because they hold
    non-routable content -- e.g. layout-adjacent files -- rather than pages.
    (This is also why a resource-level ``_layout.svelte`` doesn't get
    mistaken for a route of its own.)

    ``index.svelte`` takes precedence over ``show.svelte`` so that the root
    index route is not accidentally overridden.

    Each route's ``layout_chain`` is resolved from an optional
    ``<templates_dir>/_layout.svelte`` (root, applies to every route) and an
    optional ``<templates_dir>/<name>/_layout.svelte`` (resource, applies
    only to routes in that directory), root before resource when both exist.
    """
    if not templates_dir.is_dir():
        return []
    # app/templates -> app -> project root
    project_root = templates_dir.parent.parent
    root_layout = _root_layout(templates_dir, project_root)
    routes: List[Route] = []
    for child in sorted(templates_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("_"):
            continue
        for candidate in ("index.svelte", "show.svelte"):
            entry = child / candidate
            if entry.is_file():
                chain: List[LayoutRef] = []
                if root_layout is not None:
                    chain.append(root_layout)
                resource_layout = _resource_layout(templates_dir, project_root, child.name)
                if resource_layout is not None:
                    chain.append(resource_layout)
                routes.append(Route(name=child.name, entry_path=entry.resolve(), layout_chain=chain))
                break
    return routes


def discover_all_layouts(templates_dir: Path) -> List[LayoutRef]:
    """Return every unique layout in the app (root + one per resource that
    has one), deduped, for build-time standalone compilation. Order is root
    first (if present), then resources in sorted directory order."""
    if not templates_dir.is_dir():
        return []
    project_root = templates_dir.parent.parent
    layouts: List[LayoutRef] = []
    root_layout = _root_layout(templates_dir, project_root)
    if root_layout is not None:
        layouts.append(root_layout)
    for child in sorted(templates_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        resource_layout = _resource_layout(templates_dir, project_root, child.name)
        if resource_layout is not None:
            layouts.append(resource_layout)
    return layouts
