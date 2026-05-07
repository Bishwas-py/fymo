"""Generate per-route client entry stubs for esbuild."""
import os
from pathlib import Path
from typing import Dict, Iterable
from fymo.build.discovery import Route


CLIENT_ENTRY_TEMPLATE = """\
import {{ hydrate, mount, unmount }} from 'svelte';
import {{ stringify, parse }} from 'devalue';
import Component from '{component_import}';

// Re-export the route's Svelte component so the soft-nav router can
// dynamic-`import()` this bundle later and pluck `.default` without
// re-running the boot logic below.
export default Component;

// Boot only on the FIRST script load. When softNav dynamic-imports another
// route's bundle, this guard skips the hydrate + listener setup; the new
// bundle just contributes its component default to the import cache.
if (typeof window !== 'undefined' && !window.__fymoBooted) {{
window.__fymoBooted = true;

const propsEl = document.getElementById('svelte-props');
const initialProps = propsEl ? JSON.parse(propsEl.textContent) : {{}};
const docEl = document.getElementById('svelte-doc');
let currentDoc = docEl ? JSON.parse(docEl.textContent) : {{}};
globalThis.getDoc = () => currentDoc;

function b64url(s) {{
    return btoa(s).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
}}
async function __rpc(hash, name, args) {{
    const res = await fetch(`/_fymo/remote/${{hash}}/${{name}}`, {{
        method: 'POST', credentials: 'same-origin',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ payload: b64url(stringify(args)) }}),
    }});
    let env;
    try {{ env = await res.json(); }}
    catch (e) {{ throw new Error('invalid response'); }}
    if (env.type === 'redirect') {{ window.location.href = env.location; return; }}
    if (env.type === 'error') {{
        const e = new Error(env.error);
        e.status = env.status; e.error = env.error; e.issues = env.issues;
        throw e;
    }}
    return parse(env.result);
}}
function __resolveRemoteProps(p) {{
    for (const k in p) {{
        const v = p[k];
        if (v && typeof v === 'object' && v.__fymo_remote) {{
            const sep = v.__fymo_remote.indexOf('/');
            const hash = v.__fymo_remote.slice(0, sep);
            const name = v.__fymo_remote.slice(sep + 1);
            p[k] = (...args) => __rpc(hash, name, args);
        }}
    }}
    return p;
}}
__resolveRemoteProps(initialProps);

// --- Soft navigation ---
const target = document.getElementById('svelte-app');
let currentMount = hydrate(Component, {{ target, props: initialProps }});
let inflight = null;

const loadedCss = new Set();
function ensureCss(url) {{
    if (loadedCss.has(url)) return Promise.resolve();
    if (document.querySelector(`link[rel="stylesheet"][href="${{url}}"]`)) {{
        loadedCss.add(url);
        return Promise.resolve();
    }}
    return new Promise((resolve, reject) => {{
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = url;
        link.onload = () => {{ loadedCss.add(url); resolve(); }};
        link.onerror = () => reject(new Error('failed to load ' + url));
        document.head.appendChild(link);
    }});
}}

async function softNav(path, push = true) {{
    if (inflight) inflight.abort();
    const ctrl = new AbortController();
    inflight = ctrl;
    let res;
    try {{
        res = await fetch('/_fymo/data' + path, {{ signal: ctrl.signal, credentials: 'same-origin' }});
    }} catch (e) {{
        if (e.name === 'AbortError') return;
        window.location.href = path;
        return;
    }}
    let env;
    try {{ env = await res.json(); }}
    catch (e) {{ window.location.href = path; return; }}
    if (env.type === 'error') {{ window.location.href = path; return; }}
    inflight = null;

    const data = parse(env.result);
    const leaf = data.leaf;

    // Block on CSS to avoid FOUC.
    if (leaf.css && leaf.css.length) {{
        try {{ await Promise.all(leaf.css.map(ensureCss)); }} catch (_) {{}}
    }}

    let mod;
    try {{ mod = await import(leaf.module); }}
    catch (e) {{ window.location.href = path; return; }}
    const NewComponent = mod.default;
    if (!NewComponent) {{ window.location.href = path; return; }}

    __resolveRemoteProps(leaf.props);

    if (currentMount) {{
        try {{ unmount(currentMount); }} catch (_) {{}}
    }}
    target.innerHTML = '';
    currentMount = mount(NewComponent, {{ target, props: leaf.props }});

    currentDoc = data.doc || {{}};
    if (data.title) document.title = data.title;
    if (push) history.pushState({{ path }}, '', path);
    window.scrollTo(0, 0);
    window.dispatchEvent(new CustomEvent('fymo:navigate', {{ detail: {{ path, leaf }} }}));
}}

// Resources whose soft_nav: false in fymo.yml. Read from a meta tag set
// by the SSR layer; clicks targeting these resources skip interception so
// the browser does a full page load.
const disabledMeta = document.querySelector('meta[name="fymo-disabled-resources"]');
const disabledResources = new Set(
    (disabledMeta && disabledMeta.getAttribute('content') || '')
        .split(',').map(s => s.trim()).filter(Boolean)
);

function isDisabledResource(pathname) {{
    if (disabledResources.size === 0) return false;
    // Compare top-level path segment (e.g. "/admin/users" → "admin").
    const seg = pathname.split('/').filter(Boolean)[0];
    return seg ? disabledResources.has(seg) : false;
}}

function shouldIntercept(a, e) {{
    if (e.defaultPrevented) return false;
    if (e.button !== 0) return false;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return false;
    if (!a || a.tagName !== 'A') return false;
    if (a.target && a.target !== '_self') return false;
    if (a.hasAttribute('download')) return false;
    if (a.dataset.fymoReload !== undefined) return false;
    const href = a.getAttribute('href');
    if (!href || href.startsWith('#')) return false;
    let url;
    try {{ url = new URL(a.href, window.location.origin); }}
    catch (_) {{ return false; }}
    if (url.origin !== window.location.origin) return false;
    if (url.pathname === window.location.pathname &&
        url.search === window.location.search) return false;
    if (isDisabledResource(url.pathname)) return false;
    return url;
}}

document.addEventListener('click', (e) => {{
    const a = e.target && e.target.closest && e.target.closest('a');
    const url = shouldIntercept(a, e);
    if (!url) return;
    e.preventDefault();
    softNav(url.pathname + url.search, true);
}});

window.addEventListener('popstate', () => {{
    softNav(window.location.pathname + window.location.search, false);
}});
}}  // end !window.__fymoBooted guard
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
