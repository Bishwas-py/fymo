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
const docEl = document.getElementById('svelte-doc');
const doc = docEl ? JSON.parse(docEl.textContent) : {{}};
globalThis.getDoc = () => doc;

// Inline __resolveRemoteProps so the entry doesn't depend on the codegen
// runtime existing (apps with no app/remote/ modules don't need it).
async function __rpc(path, args) {{
    const res = await fetch('/__remote/' + path, {{
        method: 'POST', credentials: 'same-origin',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ args }}),
    }});
    const payload = await res.json().catch(() => ({{ ok: false, error: 'invalid_json' }}));
    if (payload.ok) return payload.data;
    const err = new Error(payload.message || payload.error);
    err.status = res.status; err.error = payload.error; err.issues = payload.issues;
    throw err;
}}
function __resolveRemoteProps(p) {{
    for (const k in p) {{
        const v = p[k];
        if (v && typeof v === 'object' && v.__fymo_remote) {{
            const path = v.__fymo_remote;
            p[k] = (...args) => __rpc(path, args);
        }}
    }}
}}
__resolveRemoteProps(props);

const target = document.getElementById('svelte-app');
hydrate(Component, {{ target, props }});
"""

SSE_SNIPPET = """
// Dev-only: live reload via SSE
if (typeof EventSource !== 'undefined') {
    const es = new EventSource('/_dev/reload');
    es.onmessage = (e) => { if (e.data === 'reload') location.reload(); };
}
"""


def write_client_entries(
    routes: Iterable[Route],
    out_dir: Path,
    project_root: Path,
    dev: bool = False,
) -> Dict[str, Path]:
    """Write a client entry per route, returning {route_name: entry_path}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # Resolve out_dir to a canonical path so that os.path.relpath works correctly
    # even on macOS where /var is a symlink to /private/var.
    out_dir_resolved = out_dir.resolve()
    written: Dict[str, Path] = {}
    sse_snippet = SSE_SNIPPET if dev else ""
    for route in routes:
        rel = os.path.relpath(route.entry_path, out_dir_resolved)
        # esbuild needs forward slashes in import paths
        component_import = rel.replace(os.sep, "/")
        if not component_import.startswith("."):
            component_import = "./" + component_import
        body = CLIENT_ENTRY_TEMPLATE.format(component_import=component_import) + sse_snippet
        entry_path = out_dir / f"{route.name}.client.js"
        entry_path.write_text(body)
        written[route.name] = entry_path
    return written
