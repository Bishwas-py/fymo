"""Minimal HTML builder. Reads from manifest, produces response under 10KB."""
import json
from typing import Any, Dict
from fymo.build.manifest import RouteAssets


def _safe_json(obj: Any) -> str:
    """JSON serialize and escape for safe embedding in <script type=application/json>.

    Per HTML5: such a script's content must not contain `</script` (case-insensitive).
    We escape `<`, `>`, `&` to their \\uXXXX equivalents — JSON-compatible and safe.
    """
    return (
        json.dumps(obj)
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
) -> str:
    """Render the minimal HTML envelope. Pieces are concatenated with no boilerplate."""
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
    return (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n"
        f"{head_extra}"
        f"{css_link}"
        f'<link rel="modulepreload" href="{asset_prefix}/{assets.client}">\n'
        f"{preload}"
        "</head>\n"
        "<body>\n"
        f'<div id="svelte-app">{body}</div>\n'
        f'<script type="application/json" id="svelte-props">{_safe_json(props)}</script>\n'
        f"{doc_island}"
        f'<script type="module" src="{asset_prefix}/{assets.client}"></script>\n'
        "</body>\n"
        "</html>\n"
    )
