"""Shared esbuild-metafile -> manifest-asset matching.

Used by both `BuildPipeline` (`fymo build`) and `DevOrchestrator`
(`fymo dev`) so the two build entry points can't drift the way
`DevOrchestrator`'s manifest writing once did: it was never updated when
the layout system's fields (`layout_chain`, `uses_layout_shell`, `layouts`,
`global_css`) were added to `BuildPipeline`, so `fymo dev` kept silently
writing pre-layout-system manifests (empty `layout_chain` for every route)
long after `fymo build` was already correct -- a route with a real layout
chain would get a layout-aware client bundle (from `entry_generator.py`,
which reads `route.layout_chain` directly) but flat, non-nested SSR props
(from `template_renderer.py`, which reads the manifest), crashing the
client at hydration time (`Cannot read properties of undefined
(reading 'root')`) since the two disagreed on the prop shape.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fymo.build.manifest import LayoutAssets, LayoutRefAsset, RouteAssets


def match_esbuild_outputs(
    client_outputs: Dict[str, Any],
    routes: List[Any],
    all_layouts: List[Any],
    project_root: Path,
    dist_dir: Path,
    has_global_css: bool,
) -> Tuple[Dict[str, RouteAssets], Dict[str, LayoutAssets], Optional[str]]:
    """Walk an esbuild client metafile's `outputs` and match each output
    back to the route, layout, or global-css entry point that produced it.

    Returns (route_assets, layout_assets, global_css_path). A route or
    layout with no matching output is simply absent from the returned
    dicts -- callers decide their own policy for that (BuildPipeline raises
    a hard BuildError; DevOrchestrator skips writing the manifest and waits
    for the next rebuild, since a route's output can be transiently absent
    mid-rebuild while watching).
    """
    dist_dir_abs = dist_dir.resolve()
    project_root_abs = project_root.resolve()

    def abs_out(out_path: str) -> Path:
        p = Path(out_path)
        if p.is_absolute():
            return p
        return (project_root_abs / p).resolve()

    client_by_route: Dict[str, str] = {}
    css_by_route: Dict[str, str] = {}
    layout_client: Dict[str, str] = {}
    layout_css: Dict[str, str] = {}
    global_css_out: Optional[str] = None

    for out_path, info in client_outputs.items():
        entry_point = info.get("entryPoint")
        if entry_point is None:
            continue
        abs_path = abs_out(out_path)
        try:
            rel_to_dist = abs_path.relative_to(dist_dir_abs)
        except ValueError:
            continue
        entry_name = Path(entry_point).name
        if not str(rel_to_dist).endswith(".js") and not str(rel_to_dist).endswith(".css"):
            continue

        matched_route = next((r for r in routes if entry_name == f"{r.name}.client.js"), None)
        if matched_route is not None:
            client_by_route[matched_route.name] = str(rel_to_dist).replace("\\", "/")
            css_bundle = info.get("cssBundle")
            if css_bundle:
                try:
                    css_rel = abs_out(css_bundle).relative_to(dist_dir_abs)
                    css_by_route[matched_route.name] = str(css_rel).replace("\\", "/")
                except ValueError:
                    pass
            continue

        # Layout entries are keyed in clientEntries as "_layout-<id>" but
        # their source file is the raw _layout.svelte (no per-route stub
        # like routes get from entry_generator.py), so esbuild's metafile
        # `entryPoint` is the .svelte source path -- its basename never
        # matches "_layout-<id>.js". `ref.id` is an unsanitized directory
        # name (see discovery.py), so it can itself contain "." -- e.g.
        # resource dirs "a" and "a.b" both -- which would make a
        # string-prefix match on the hashed output filename ambiguous.
        # Match by path identity instead: resolve entry_point the same way
        # abs_out() resolves other paths here, and compare it to
        # ref.svelte_path, mirroring the route branch's identity match.
        if not str(rel_to_dist).endswith(".js"):
            matched_layout = None
        else:
            entry_point_abs = abs_out(entry_point)
            matched_layout = next(
                (ref for ref in all_layouts if entry_point_abs == ref.svelte_path.resolve()),
                None,
            )
        if matched_layout is not None:
            layout_client[matched_layout.id] = str(rel_to_dist).replace("\\", "/")
            css_bundle = info.get("cssBundle")
            if css_bundle:
                try:
                    css_rel = abs_out(css_bundle).relative_to(dist_dir_abs)
                    layout_css[matched_layout.id] = str(css_rel).replace("\\", "/")
                except ValueError:
                    pass
            continue

        if has_global_css and entry_name == "_global.css" and str(rel_to_dist).endswith(".css"):
            global_css_out = str(rel_to_dist).replace("\\", "/")

    chunks: List[str] = []
    for p in client_outputs:
        if Path(p).name.startswith("chunk-") and p.endswith(".js"):
            try:
                rel = abs_out(p).relative_to(dist_dir_abs)
                chunks.append(str(rel).replace("\\", "/"))
            except ValueError:
                pass

    route_assets = {
        r.name: RouteAssets(
            ssr=f"ssr/{r.name}.mjs",
            client=client_by_route[r.name],
            css=css_by_route.get(r.name),
            preload=chunks,
            layout_chain=[
                LayoutRefAsset(level=ref.level, id=ref.id, controller_module=ref.controller_module)
                for ref in r.layout_chain
            ],
            uses_layout_shell=bool(r.layout_chain),
        )
        for r in routes
        if r.name in client_by_route
    }

    layout_assets = {
        ref.id: LayoutAssets(client=layout_client[ref.id], css=layout_css.get(ref.id))
        for ref in all_layouts
        if ref.id in layout_client
    }

    return route_assets, layout_assets, global_css_out
