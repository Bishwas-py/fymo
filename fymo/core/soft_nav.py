"""Soft-navigation data endpoint.

Serves `GET /_fymo/data/<path>` so the client router can fetch the next
page's props + asset URLs without a full HTML reload.

Wire format (always HTTP 200; errors carried in the envelope):

    {"type": "result", "result": "<devalue>"}      # success
    {"type": "error", "status": 404, "error": "not_found"}

The decoded result has the shape:

    {
      "leaf": {
        "id":     "posts",                          # manifest route key
        "module": "/dist/client/posts.A1B2.js",     # absolute URL of leaf bundle
        "css":    ["/dist/client/posts.A1B2.css"],  # may be empty
        "props":  { ... },                           # devalue-serialized
        "usesLayoutShell": True,                    # False for routes with no layout_chain
        "resourceLayout": {                         # or None when no resource-level layout
          "id":     "posts",
          "module": "/dist/client/layouts/posts.C3D4.js",
          "css":    ["/dist/client/layouts/posts.C3D4.css"],
          "props":  { ... },
        },
        "rootLayoutProps": { ... },                 # or None when no root-level layout
      },
      "title":  "Post: Welcome",
      "doc":    { ... }                             # merged getDoc() output (root -> resource -> leaf)
    }

The `doc`/`title` merge and layout-prop loading go through the exact same
`ssr_controller.load_layout_props_and_docs`/`merge_docs` helpers the
full-page SSR path (`template_renderer.py`) uses, so the two call sites
can't drift apart the way they once did for `current_user()` scoping (see
`ssr_controller`'s module docstring).

The client uses `id` for chain-diffing in PR B; in PR A every nav swaps
the leaf unconditionally.
"""
from __future__ import annotations

import json
import traceback
from typing import Iterable

from fymo.core.html import _safe_json
from fymo.core.manifest_cache import ManifestUnavailable
from fymo.core.ssr_controller import load_controller_context, load_layout_props_and_docs, merge_docs
from fymo.remote import devalue


_PATH_PREFIX = "/_fymo/data/"
_ASSET_PREFIX = "/dist"


def _200(start_response, payload: dict) -> Iterable[bytes]:
    body = json.dumps(payload).encode("utf-8")
    start_response("200 OK", [
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
    ])
    return [body]


def handle_data(app, environ: dict, start_response) -> Iterable[bytes]:
    """Resolve the route, invoke its controller, return its leaf assets + props."""
    path_info = environ.get("PATH_INFO", "")
    if not path_info.startswith(_PATH_PREFIX):
        return _200(start_response, {"type": "error", "status": 400, "error": "bad_path"})

    route_path = path_info[len(_PATH_PREFIX) - 1:]  # keep leading "/"
    if not route_path:
        route_path = "/"

    route_info = app.router.match(route_path)
    if not route_info:
        return _200(start_response, {"type": "error", "status": 404, "error": "no_route"})

    controller_name = route_info["controller"]

    # Per-resource opt-out from soft navigation. The client preempts via the
    # fymo-disabled-resources meta tag, but we still answer here in case a
    # stale client (or a hand-rolled fetch) hits the endpoint anyway.
    if not app.router.soft_nav_enabled(controller_name):
        return _200(start_response, {"type": "error", "status": 409, "error": "soft_nav_disabled"})

    # Manifest lookup — controller name is the route key.
    try:
        manifest = app.manifest_cache.get()
    except ManifestUnavailable as e:
        return _200(start_response, {"type": "error", "status": 503, "error": "no_manifest", "message": str(e)})

    assets = manifest.routes.get(controller_name)
    if assets is None:
        return _200(start_response, {"type": "error", "status": 404, "error": "no_bundle"})

    # Invoke the controller exactly like full-page SSR would.
    import importlib
    try:
        controller_mod = importlib.import_module(f"app.controllers.{controller_name}")
    except ImportError:
        return _200(start_response, {"type": "error", "status": 404, "error": "no_controller"})

    params = route_info.get("params", {}) or {}

    # Invoke exactly like full-page SSR does, including the (optional)
    # read-only auth request scope so current_user() resolves the same way
    # on both the full-page render and this soft-nav path -- see
    # ssr_controller for why this must be the same helper both call.
    try:
        leaf_props, leaf_doc = load_controller_context(
            controller_mod, params, getattr(app, "auth_enabled", False), environ
        )
        layout_props_by_level = {"root": {}, "resource": {}}
        layout_docs = []
        if assets.layout_chain:
            layout_props_by_level, layout_docs = load_layout_props_and_docs(
                assets.layout_chain, params, getattr(app, "auth_enabled", False), environ
            )
    except Exception as e:
        payload = {"type": "error", "status": 500, "error": "controller_failed"}
        if getattr(app, "dev", False):
            payload["message"] = str(e)
            payload["traceback"] = traceback.format_exc()
        return _200(start_response, payload)

    doc_meta = merge_docs(layout_docs + [leaf_doc]) if assets.layout_chain else leaf_doc

    # Round-trip props through _safe_json so remote callables become
    # {"__fymo_remote": "<hash>/<fn>"} markers (same shape as full-page SSR).
    serialized_leaf_props = json.loads(_safe_json(leaf_props))

    css_urls = [f"{_ASSET_PREFIX}/{assets.css}"] if assets.css else []
    preload_urls = [f"{_ASSET_PREFIX}/{p}" for p in assets.preload]

    resource_layout_payload = None
    root_layout_props_payload = None
    if assets.layout_chain:
        resource_ref = next((ref for ref in assets.layout_chain if ref.level == "resource"), None)
        if resource_ref is not None:
            layout_asset = app.manifest_cache.get().layouts.get(resource_ref.id)
            if layout_asset is not None:
                resource_css = [f"{_ASSET_PREFIX}/{layout_asset.css}"] if layout_asset.css else []
                resource_layout_payload = {
                    "id": resource_ref.id,
                    "module": f"{_ASSET_PREFIX}/{layout_asset.client}",
                    "css": resource_css,
                    "props": json.loads(_safe_json(layout_props_by_level.get("resource", {}))),
                }
        root_ref = next((ref for ref in assets.layout_chain if ref.level == "root"), None)
        if root_ref is not None:
            root_layout_props_payload = json.loads(_safe_json(layout_props_by_level.get("root", {})))

    leaf = {
        "id": controller_name,
        "module": f"{_ASSET_PREFIX}/{assets.client}",
        "css": css_urls,
        "preload": preload_urls,
        "props": serialized_leaf_props,
        "usesLayoutShell": assets.uses_layout_shell,
        "resourceLayout": resource_layout_payload,
        "rootLayoutProps": root_layout_props_payload,
    }

    title = doc_meta.get("title", app.config_manager.get_app_name())

    try:
        encoded = devalue.stringify({"leaf": leaf, "title": title, "doc": doc_meta})
    except Exception as e:
        payload = {"type": "error", "status": 500, "error": "encode_failed"}
        if getattr(app, "dev", False):
            payload["message"] = str(e)
        return _200(start_response, payload)

    return _200(start_response, {"type": "result", "result": encoded})
