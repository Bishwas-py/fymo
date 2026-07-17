"""Neutral raw-WSGI-route primitive for apps that need a route outside the
remote-function / SSR-page model (binary/range media serving, webhooks,
OAuth callback endpoints, etc.).
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List


@dataclass(frozen=True)
class HttpRoute:
    """A raw WSGI route mounted outside fymo's remote-function/SSR routing.

    `path` is matched as a PREFIX against the request path — the same style
    fymo already uses for its own `/dist/` and `/static/` static routes in
    `FymoApp._dispatch` — not an exact match and not a templated pattern
    (no `<param>` syntax). `handler` is a WSGI-style callable
    `(environ, start_response) -> iterable` responsible for parsing anything
    after the matched prefix itself (e.g. a filename segment).
    """
    method: str
    path: str
    handler: Callable


def discover_app_http_routes(project_root: Path) -> List[HttpRoute]:
    """Load `app/routes.py`'s `http_routes()` if present, else return `[]`.

    Optional extension point — most apps never need this (SSR pages and
    remote functions cover almost everything). Loaded once at FymoApp init
    via `importlib.util.spec_from_file_location` under a project-root-unique
    module name, so two different projects' `app/routes.py` never collide in
    `sys.modules` within the same process (matters for a test session that
    instantiates multiple FymoApps against different tmp_path roots).

    Not to be confused with `config/routes.py`, which declares SSR page
    routes (`root`/`resources`) consumed by `Router` — a completely separate
    file, directory, and schema. This one is for raw WSGI routes only.
    """
    routes_file = Path(project_root) / "app" / "routes.py"
    if not routes_file.is_file():
        return []

    mod_name = f"_fymo_app_routes_{abs(hash(str(routes_file.resolve())))}"
    spec = importlib.util.spec_from_file_location(mod_name, routes_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load {routes_file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)

    fn = getattr(module, "http_routes", None)
    if fn is None:
        return []
    routes = fn()
    if not isinstance(routes, list):
        raise TypeError(
            f"app/routes.py: http_routes() must return a list of HttpRoute, "
            f"got {type(routes).__name__}"
        )
    return routes
