"""Generate per-route client entry stubs for esbuild."""
import os
from pathlib import Path
from typing import Dict, Iterable
from fymo.build.discovery import Route


CLIENT_ENTRY_TEMPLATE = """\
import {{ hydrate }} from 'svelte';
import Component from '{component_import}';

const propsEl = document.getElementById('svelte-props');
const props = propsEl ? JSON.parse(propsEl.textContent) : {{}};
const target = document.getElementById('svelte-app');

hydrate(Component, {{ target, props }});
"""


def write_client_entries(routes: Iterable[Route], out_dir: Path, project_root: Path) -> Dict[str, Path]:
    """Write a client entry per route, returning {route_name: entry_path}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: Dict[str, Path] = {}
    for route in routes:
        rel = os.path.relpath(route.entry_path, out_dir)
        # esbuild needs forward slashes in import paths
        component_import = rel.replace(os.sep, "/")
        if not component_import.startswith("."):
            component_import = "./" + component_import
        entry_path = out_dir / f"{route.name}.client.js"
        entry_path.write_text(CLIENT_ENTRY_TEMPLATE.format(component_import=component_import))
        written[route.name] = entry_path
    return written
