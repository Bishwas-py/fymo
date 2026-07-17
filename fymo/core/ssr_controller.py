"""Shared controller-invocation logic for SSR data paths.

Both the full-page render (`template_renderer.TemplateRenderer._load_controller_data`)
and the soft-nav data endpoint (`soft_nav.handle_data`, serving
`GET /_fymo/data/<path>`) need to do the exact same thing: import a
controller module, call its `getContext(**accepted_params)` and `getDoc()`,
inside the same read-only request scope that lets `current_uid()` resolve
the request's identity, mirroring the scope remote functions get.

Previously each call site re-implemented this by hand, and the soft-nav path
was built without the request-scope wrapping, so identity resolution worked
during a full page load but raised `RuntimeError` (-> 500 controller_failed)
on every soft-nav transition, which is fymo's default navigation mode. This
module is the single implementation both paths call so they can't drift
apart again.
"""
from __future__ import annotations

import inspect
from contextlib import nullcontext
from typing import Any, Dict, List, Tuple


def ssr_request_scope(environ: dict | None):
    """Context manager opened around getContext()/getDoc() during SSR/soft-nav.

    When a request environ is available, this opens the same `request_scope`
    remote functions use, so `current_uid()` and `request_event()` resolve
    inside a controller exactly like they would from a remote call. This
    is what removes the logged-out flash (both the full-page render and the
    soft-nav data endpoint can return identity-aware props instead of always
    rendering logged-out and waiting for client hydration to fix it up).

    Deliberately read-only: unlike the remote router, this does NOT call
    start_auth_scope()/consume_pending_cookies(). Both call sites serve a
    GET, not a login POST: there is nothing to set a cookie for, and
    current_uid() only reads `_current_event`, so the cookie-queue
    machinery is unnecessary here.

    A no-op nullcontext() when no environ was threaded down (e.g.
    render_template() called directly without one, as some existing tests
    do), current_uid() then raises its outside-a-scope RuntimeError, the
    same answer a remote function called outside a request gets.
    """
    if environ is None:
        return nullcontext()
    from fymo.remote.identity import _ensure_uid
    from fymo.remote.context import request_scope

    # Set-Cookie is discarded: neither call site issues a fresh fymo_uid
    # cookie (only the remote/router path does), we only need the uid value
    # to build the same RequestEvent shape resolvers expect.
    uid, _set_cookie = _ensure_uid(environ)
    return request_scope(uid=uid, environ=environ)


def load_controller_context(
    controller: Any,
    params: dict | None,
    environ: dict | None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Call controller.getContext(**accepted)/getDoc(), inside a request scope.

    `accepted` is `params` filtered down to the keyword names getContext's
    signature actually declares, same convention route params have always
    used. Wrapped in `ssr_request_scope(...)` so current_uid() works
    identically whether the caller is the full-page renderer or the
    soft-nav data endpoint.
    """
    params = params or {}
    with ssr_request_scope(environ):
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


def load_layout_props_and_docs(
    layout_chain,
    params: dict | None,
    environ: dict | None,
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """Invoke each layout's controller (if any) the same way leaf controllers
    are invoked, via load_controller_context() -- same accepted-params
    filtering, same ssr_request_scope wrapping, so current_uid() resolves
    identically in a layout as it does in a page controller or a remote
    function.

    `layout_chain` is an iterable of objects with `.level` ("root" |
    "resource"), `.id`, and `.controller_module` (dotted path, or None) --
    in practice fymo.build.manifest.LayoutRefAsset. A level with no
    controller_module (no _layout.py file) contributes {} to props and is
    skipped for docs (nothing to merge). Import errors for a
    controller_module that IS set are not caught here -- discovery only
    ever sets controller_module when the file exists on disk, so a failure
    to import it is a real bug in the app and should propagate the same way
    a broken leaf controller's ImportError would.
    """
    import importlib

    props_by_level: Dict[str, Dict[str, Any]] = {"root": {}, "resource": {}}
    docs_in_order: List[Dict[str, Any]] = []
    for ref in layout_chain:
        if ref.controller_module is None:
            continue
        controller = importlib.import_module(ref.controller_module)
        props, doc = load_controller_context(controller, params, environ)
        props_by_level[ref.level] = props
        docs_in_order.append(doc)
    return props_by_level, docs_in_order


def merge_docs(docs_in_order: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Shallow-merge getDoc() dicts in the given order (root -> resource ->
    leaf, by convention of what the caller passes in). Later entries win on
    scalar keys. `head.meta` and `head.link` lists concatenate across every
    dict that defines them, in order, instead of the later one overwriting
    the earlier one -- a leaf's page-specific <meta> should add to, not
    erase, the root layout's defaults."""
    merged: Dict[str, Any] = {}
    meta_acc: List[Any] = []
    link_acc: List[Any] = []
    head_seen = False
    for doc in docs_in_order:
        for key, value in doc.items():
            if key == "head" and isinstance(value, dict):
                head_seen = True
                meta_acc.extend(value.get("meta") or [])
                link_acc.extend(value.get("link") or [])
                for head_key, head_value in value.items():
                    if head_key in ("meta", "link"):
                        continue
                    merged.setdefault("head", {})
                    merged["head"][head_key] = head_value
            else:
                merged[key] = value
    if head_seen:
        merged.setdefault("head", {})
        merged["head"]["meta"] = meta_acc
        merged["head"]["link"] = link_acc
    return merged
