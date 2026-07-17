"""Import app/auth/*.py so @identify resolvers self-register (issue #80).

Presence of resolvers in app/auth/ is what turns the new identity system
on; deleting the directory turns it off. No config key gates it. Mirrors
fymo.core.app_discovery's walk (sys.path insert/remove, parent-package
eviction, evict + fresh import) but collects nothing: executing each
module body is the whole point, the @identify decorator does the
registering, and identify's definition-site dedup makes repeated imports
(server boot, build hygiene, dev restarts) idempotent.

app/auth/ modules are backend code like app/remote/, but they are NOT
remote modules: fymo.remote.discovery globs only app/remote/*.py and this
walk globs only app/auth/*.py, so neither is ever scanned by the other or
emitted to the client.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import List

from fymo.core.app_discovery import _ensure_parent_packages


def _prune_stale_app_resolvers(project_root: Path) -> None:
    """Drop registered resolvers claiming an app.auth.* module whose defining
    file lives outside this project root: leftovers from a previous project
    loaded in the same process (a test session, a moved dev root). Mirrors
    the app.* sys.modules eviction FymoApp.__init__ performs."""
    from fymo.auth import identity as _identity

    root = Path(project_root).resolve()
    kept = []
    for fn in _identity._identity_resolvers:
        module = getattr(fn, "__module__", "") or ""
        if module == "app.auth" or module.startswith("app.auth."):
            code = getattr(fn, "__code__", None)
            filename = getattr(code, "co_filename", "") if code else ""
            try:
                Path(filename).resolve().relative_to(root)
            except (ValueError, OSError):
                continue
        kept.append(fn)
    _identity._identity_resolvers[:] = kept


def import_auth_modules(project_root: Path) -> List[str]:
    """Import every non-private module under app/auth/ so its @identify
    resolvers self-register. Returns the imported dotted module names in
    import (sorted-filename) order; [] when app/auth/ does not exist.

    Modules named __init__.py or with a leading underscore are not imported
    directly (same convention as app/remote/); private helpers are reached
    transitively by the modules that import them. Evict + fresh import,
    never importlib.reload, for the same reason app_discovery does it:
    reload reuses the module __dict__ and would leak stale definitions."""
    project_root = Path(project_root)
    auth_dir = project_root / "app" / "auth"
    if not auth_dir.is_dir():
        return []

    _prune_stale_app_resolvers(project_root)

    project_root_str = str(project_root)
    added = project_root_str not in sys.path
    if added:
        sys.path.insert(0, project_root_str)
    try:
        _ensure_parent_packages(project_root, "auth")
        imported: List[str] = []
        for py in sorted(auth_dir.glob("*.py")):
            if py.name == "__init__.py" or py.stem.startswith("_"):
                continue
            full = f"app.auth.{py.stem}"
            if full in sys.modules:
                del sys.modules[full]
            importlib.import_module(full)
            imported.append(full)
        return imported
    finally:
        if added and project_root_str in sys.path:
            sys.path.remove(project_root_str)
