"""Shared controller-invocation logic for SSR data paths.

Both the full-page render (`template_renderer.TemplateRenderer._load_controller_data`)
and the soft-nav data endpoint (`soft_nav.handle_data`, serving
`GET /_fymo/data/<path>`) need to do the exact same thing: import a
controller module, call its `getContext(**accepted_params)` and `getDoc()`,
and -- when auth is enabled -- do so inside the same read-only request scope
that lets `current_user()` resolve the session cookie, mirroring the scope
remote functions get.

Previously each call site re-implemented this by hand, and the soft-nav path
was built without the request-scope wrapping, so `current_user()` worked
during a full page load but raised `RuntimeError` (-> 500 controller_failed)
on every soft-nav transition, which is fymo's default navigation mode. This
module is the single implementation both paths call so they can't drift
apart again.
"""
from __future__ import annotations

import inspect
from contextlib import nullcontext
from typing import Any, Dict, Tuple


def ssr_request_scope(auth_enabled: bool, environ: dict | None):
    """Context manager opened around getContext()/getDoc() during SSR/soft-nav.

    When auth is enabled and a request environ is available, this opens the
    same `request_scope` remote functions use, so `current_user()` and
    `request_event()` resolve inside a controller exactly like they would
    from a remote call -- this is what removes the logged-out flash (both
    the full-page render and the soft-nav data endpoint can return
    user-aware props instead of always rendering logged-out and waiting for
    client hydration to fix it up).

    Deliberately read-only: unlike the remote router, this does NOT call
    start_auth_scope()/consume_pending_cookies(). Both call sites serve a
    GET, not a login/signup POST -- there is nothing to set a cookie for,
    and current_user() only reads `_current_event`, so the cookie-queue
    machinery is unnecessary here.

    A no-op nullcontext() when auth is disabled or no environ was threaded
    down (e.g. render_template() called directly without one, as some
    existing tests do) -- behavior-preserving for apps that don't use auth
    and for direct callers.
    """
    if not auth_enabled or environ is None:
        return nullcontext()
    from fymo.remote.identity import _ensure_uid
    from fymo.remote.context import request_scope

    # Set-Cookie is discarded: neither call site issues a fresh fymo_uid
    # cookie (only the remote/router path does), we only need the uid value
    # to build the same RequestEvent shape current_user() expects.
    uid, _set_cookie = _ensure_uid(environ)
    return request_scope(uid=uid, environ=environ)


def load_controller_context(
    controller: Any,
    params: dict | None,
    auth_enabled: bool,
    environ: dict | None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Call controller.getContext(**accepted)/getDoc(), scoped for auth.

    `accepted` is `params` filtered down to the keyword names getContext's
    signature actually declares, same convention route params have always
    used. Wrapped in `ssr_request_scope(...)` so current_user() works
    identically whether the caller is the full-page renderer or the
    soft-nav data endpoint.
    """
    params = params or {}
    with ssr_request_scope(auth_enabled, environ):
        props: Dict[str, Any] = {}
        getContext = getattr(controller, "getContext", None)
        if callable(getContext):
            sig = inspect.signature(getContext)
            accepted = {k: v for k, v in params.items() if k in sig.parameters}
            props = getContext(**accepted) or {}

        doc_meta: Dict[str, Any] = {}
        getDoc = getattr(controller, "getDoc", None)
        if callable(getDoc):
            doc_meta = getDoc() or {}

    return props, doc_meta
