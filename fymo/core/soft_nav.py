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
        "props":  { ... }                            # devalue-serialized
      },
      "title":  "Post: Welcome",
      "doc":    { ... }                             # full controller getDoc() output
    }

The client uses `id` for chain-diffing in PR B; in PR A every nav swaps
the leaf unconditionally.
"""
from __future__ import annotations

import inspect
import json
import traceback
from typing import Iterable

from fymo.core.html import _safe_json
from fymo.core.manifest_cache import ManifestUnavailable
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

    props: dict = {}
    doc_meta: dict = {}
    try:
        if hasattr(controller_mod, "getContext") and callable(controller_mod.getContext):
            sig = inspect.signature(controller_mod.getContext)
            accepted = {k: v for k, v in params.items() if k in sig.parameters}
            props = controller_mod.getContext(**accepted) or {}
        if hasattr(controller_mod, "getDoc") and callable(controller_mod.getDoc):
            doc_meta = controller_mod.getDoc() or {}
    except Exception as e:
        payload = {"type": "error", "status": 500, "error": "controller_failed"}
        if getattr(app, "dev", False):
            payload["message"] = str(e)
            payload["traceback"] = traceback.format_exc()
        return _200(start_response, payload)

    # Round-trip props through _safe_json so remote callables become
    # {"__fymo_remote": "<hash>/<fn>"} markers (same shape as full-page SSR).
    serialized_props = json.loads(_safe_json(props))

    css_urls = [f"{_ASSET_PREFIX}/{assets.css}"] if assets.css else []
    preload_urls = [f"{_ASSET_PREFIX}/{p}" for p in assets.preload]

    leaf = {
        "id": controller_name,
        "module": f"{_ASSET_PREFIX}/{assets.client}",
        "css": css_urls,
        "preload": preload_urls,
        "props": serialized_props,
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
