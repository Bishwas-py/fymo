"""Route-level require_auth enforcement for page loads (issue #80 phase 2).

fymo.yml routes carry exactly one auth attribute, `require_auth`:

    true                          -> the request must resolve a uid via the
                                     @identify chain (fymo.auth.current_uid)
    "app.auth.guards.require_x"   -> the signed-in check first, then the
                                     dotted-path guard is imported and called
                                     zero-arg inside the request scope

Failure is an HTTP redirect to the route named `signin` (a convention, not
an attribute) with the originally requested path carried as ?next=. Only
the path+query of the original request is ever carried, never an absolute
URL. In this phase ANY exception from a guard redirects the same way; a
typed Forbidden/403 distinction for pages is a later phase.

Enforcement runs before any SSR work starts (no flash of protected content,
no wasted sidecar render) in both page-serving paths: the full-page render
(fymo/core/template_renderer.py) and the soft-nav data endpoint
(fymo/core/soft_nav.py). Both consult only the NEW identity chain; the
legacy auth: system is untouched and separately gated.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any, Callable, Optional
from urllib.parse import quote

logger = logging.getLogger("fymo")


REQUIRE_AUTH_WITHOUT_SIGNIN_ERROR = (
    "routes use `require_auth` but no route named `signin` exists. Anonymous "
    "visitors to a protected page are redirected to the signin route by "
    "convention. Add a route named signin to fymo.yml (e.g. `signin: "
    "signin.index` under routes:, or a resource named signin)."
)


def resolve_guard(dotted_path: str) -> Callable[[], Any]:
    """Import `module.attr` and return the guard callable.

    Raises ImportError/AttributeError on a bad path; callers decide whether
    that is a boot ConfigurationError (validate_route_guards) or a build
    violation (fymo/build/hygiene.py)."""
    module_path, _, attr = dotted_path.rpartition(".")
    if not module_path or not attr:
        raise ImportError(
            f"invalid guard path {dotted_path!r} (expected module.attr, "
            "e.g. app.auth.guards.require_admin)"
        )
    mod = importlib.import_module(module_path)
    guard = getattr(mod, attr)
    if not callable(guard):
        raise ImportError(f"{dotted_path} is not callable")
    return guard


def validate_route_guards(router) -> None:
    """Boot-time validation of every route's require_auth value.

    A dotted-path guard that cannot import must refuse to boot, naming the
    path, never surface as a request-time failure. Called from
    FymoApp.__init__ right after the router is built."""
    from fymo.core.exceptions import ConfigurationError

    for path, info in router.routes.items():
        if not isinstance(info, dict):
            continue
        value = info.get("require_auth")
        if value is None or value is False or value is True:
            continue
        if not isinstance(value, str):
            raise ConfigurationError(
                f"route {path!r}: require_auth must be true or a dotted guard "
                f"path string, got {type(value).__name__} ({value!r})"
            )
        try:
            resolve_guard(value)
        except Exception as e:
            raise ConfigurationError(
                f"route {path!r}: require_auth guard {value!r} could not be "
                f"imported: {e}. Fix the dotted path or define the guard "
                "(e.g. require_auth: app.auth.guards.require_admin pointing "
                "at a zero-argument function in app/auth/guards.py)."
            ) from e


def _identity_scope(environ: dict):
    """Request scope for the require_auth check, opened before SSR starts.

    Same read-only posture as ssr_controller.ssr_request_scope: no cookie
    queueing, Set-Cookie from _ensure_uid discarded. The new identity chain
    is on whenever app/auth/ registers resolvers."""
    from fymo.remote.context import request_scope
    from fymo.remote.identity import _ensure_uid

    uid, _set_cookie = _ensure_uid(environ)
    return request_scope(uid=uid, environ=environ)


def _next_param(route_path: str, environ: Optional[dict]) -> str:
    query = (environ or {}).get("QUERY_STRING", "")
    target = route_path + (f"?{query}" if query else "")
    return quote(target, safe="")


def page_auth_redirect(
    require_auth: Any,
    environ: Optional[dict],
    signin_path: Optional[str],
    route_path: str,
) -> Optional[str]:
    """Run the route's require_auth check; return the signin redirect
    location when it fails, None when the request may proceed.

    Callers gate on a truthy require_auth before calling. `environ=None`
    (a render with no request context) fails closed as anonymous. A guard
    import failure here is a server bug (boot validated it) and propagates
    as the 500 it is; only exceptions from calling the guard redirect."""
    if signin_path is None:
        raise RuntimeError(
            "require_auth is set but the router has no signin route; "
            "Router validation should have rejected this configuration at boot"
        )
    redirect_to = f"{signin_path}?next={_next_param(route_path, environ)}"
    if environ is None:
        return redirect_to

    from fymo.auth.identity import current_uid

    with _identity_scope(environ):
        if current_uid() is None:
            return redirect_to
        if require_auth is True:
            return None
        guard = resolve_guard(require_auth)
        try:
            guard()
        except Exception as e:
            logger.info(
                "require_auth guard %s rejected %s: %s", require_auth, route_path, e
            )
            return redirect_to
    return None
