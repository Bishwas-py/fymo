"""Minimal HTML builder. Reads from manifest, produces response under 10KB."""
import json
from typing import Any, Dict
from fymo.build.manifest import RouteAssets


def _lookup_remote_hash(module_name: str) -> str | None:
    """Look up a remote module's hash from the manifest. Overridable in tests."""
    from fymo.core.manifest_cache import _SHARED_CACHE
    if _SHARED_CACHE is None:
        return None
    try:
        return _SHARED_CACHE.get_remote_hash(module_name)
    except Exception:
        return None


def _remote_marker(obj):
    mod_name = getattr(obj, "__module__", None)
    if not (mod_name and mod_name.startswith("app.remote.") and callable(obj)):
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
    short = mod_name[len("app.remote."):]
    hash_ = _lookup_remote_hash(short)
    if not hash_:
        raise TypeError(
            f"remote module 'app.remote.{short}' has no hash in manifest "
            f"(did you forget to run `fymo build`?)"
        )
    return {"__fymo_remote": f"{hash_}/{obj.__name__}"}


def _safe_json(obj: Any) -> str:
    """JSON serialize and escape for safe embedding in <script type=application/json>.

    Per HTML5: such a script's content must not contain `</script` (case-insensitive).
    We escape `<`, `>`, `&` to their \\uXXXX equivalents — JSON-compatible and safe.
    """
    return (
        json.dumps(obj, default=_remote_marker)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def build_html(
    body: str,
    head_extra: str,
    props: Dict[str, Any],
    assets: RouteAssets,
    title: str,
    asset_prefix: str = "/dist",
    doc: Dict[str, Any] = None,
    disabled_soft_nav: list = None,
    layout_css: list = None,
    params: Dict[str, Any] = None,
    identity: Dict[str, Any] = None,
) -> str:
    """Render the minimal HTML envelope. Pieces are concatenated with no boilerplate.

    `layout_css` is the route's layout chain's CSS paths in chain order
    (root first, then resource), linked before the route's own CSS so the
    cascade layers general styles under specific ones.
    """
    layout_css_links = "".join(
        f'<link rel="stylesheet" href="{asset_prefix}/{c}">\n'
        for c in (layout_css or [])
    )
    css_link = (
        f'<link rel="stylesheet" href="{asset_prefix}/{assets.css}">\n'
        if assets.css else ""
    )
    preload = "".join(
        f'<link rel="modulepreload" href="{asset_prefix}/{p}">\n'
        for p in assets.preload
    )
    doc_island = (
        f'<script type="application/json" id="svelte-doc">{_safe_json(doc)}</script>\n'
        if doc is not None else ""
    )
    # Always emitted, unlike doc_island -- the client's route.js reads
    # this to seed its reactive `params` before hydrate(), and treating a
    # route with no dynamic segments as "tag absent" would force the client
    # to special-case a missing island vs a genuinely empty dict.
    route_params_island = (
        f'<script type="application/json" id="svelte-route-params">{_safe_json(params or {})}</script>\n'
    )
    # The public_identity projection output (issue #80), or null when
    # anonymous. Always emitted, like the route-params island, so the
    # $auth client never special-cases a missing tag; goes through
    # _safe_json exactly like props so it can't break out of the island.
    identity_island = (
        f'<script type="application/json" id="fymo-identity">{_safe_json(identity)}</script>\n'
    )
    # Pass the list of resources whose soft-nav is disabled to the client
    # router so it can skip click interception preemptively (no wasted
    # /_fymo/data round-trip for those URLs).
    disabled_meta = ""
    if disabled_soft_nav:
        # Resource names are alphanumeric/underscore; HTML-escape defensively anyway.
        def _esc(s: str) -> str:
            return (
                s.replace("&", "&amp;")
                .replace('"', "&quot;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
        safe = ",".join(_esc(n) for n in disabled_soft_nav)
        disabled_meta = f'<meta name="fymo-disabled-resources" content="{safe}">\n'
    return (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n"
        f"{disabled_meta}"
        f"{head_extra}"
        f"{layout_css_links}"
        f"{css_link}"
        f'<link rel="modulepreload" href="{asset_prefix}/{assets.client}">\n'
        f"{preload}"
        "</head>\n"
        "<body>\n"
        f'<div id="svelte-app">{body}</div>\n'
        f'<script type="application/json" id="svelte-props">{_safe_json(props)}</script>\n'
        f"{doc_island}"
        f"{route_params_island}"
        f"{identity_island}"
        f'<script type="module" src="{asset_prefix}/{assets.client}"></script>\n'
        "</body>\n"
        "</html>\n"
    )
