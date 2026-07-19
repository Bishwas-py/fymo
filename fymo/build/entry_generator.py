"""Generate per-route client entry stubs for esbuild."""
import os
from pathlib import Path
from typing import Dict, Iterable
from fymo.build.discovery import Route
from fymo.remote.codegen import B64URL_JS, REMOTE_ERROR_THROW_JS


CLIENT_ENTRY_TEMPLATE = """\
import {{ hydrate, mount, unmount }} from 'svelte';
import {{ stringify, parse }} from 'devalue';
import {{ seedRoute, applyRouteNav }} from '$route';
import {{ __setIdentity as __fymoSetIdentity }} from '$auth';
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

// Seed the $auth identity store from the SSR payload before
// hydrate(), so the first client render agrees with the server's.
const identityEl = document.getElementById('fymo-identity');
__fymoSetIdentity(identityEl ? JSON.parse(identityEl.textContent) : null);

// Seed the reactive route state from this request's own URL + the server's
// resolved :id-style params, before hydrate() -- so the first subscriber
// that reads it after mount already sees the right value.
seedRoute();

{b64url}
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
    {error_throw}
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
    if (env.type === 'redirect') {{ window.location.href = env.location; return; }}
    if (env.type === 'error') {{ window.location.href = path; return; }}
    inflight = null;

    const data = parse(env.result);
    __fymoSetIdentity(data.identity ?? null);
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
    applyRouteNav(path, data.params);
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


SHELL_TEMPLATE = """\
<script>
{imports}
  let {{ leafProps, layoutProps, initialLeaf, initialResourceLayout = null }} = $props();

  let CurrentLeaf = $state(initialLeaf);
  let currentLeafProps = $state(leafProps);
  let CurrentResourceLayout = $state(initialResourceLayout);
  let currentResourceLayoutProps = $state(layoutProps.resource);
  let currentRootLayoutProps = $state(layoutProps.root);

  export function swapLeaf(NewLeaf, newProps) {{
    CurrentLeaf = NewLeaf;
    currentLeafProps = newProps;
  }}
  export function swapResourceLayout(NewLayout, newProps) {{
    CurrentResourceLayout = NewLayout;
    currentResourceLayoutProps = newProps;
  }}
  export function updateRootLayoutProps(newProps) {{
    currentRootLayoutProps = newProps;
  }}
  export function updateResourceLayoutProps(newProps) {{
    currentResourceLayoutProps = newProps;
  }}

  function onLeafError(error) {{
    if (typeof console !== 'undefined') {{
      console.error('[fymo] leaf render error:', error && error.stack || error && error.message || error);
    }}
  }}
</script>

{{#snippet leafSlot()}}
  <svelte:boundary onerror={{onLeafError}}>
    <CurrentLeaf {{...currentLeafProps}} />
    {{#snippet failed(error, reset)}}
      <div class="fymo-leaf-error">Something went wrong. <button onclick={{reset}}>Retry</button></div>
    {{/snippet}}
  </svelte:boundary>
{{/snippet}}

{root_open}{resource_block}{root_close}"""

SHELL_ROOT_OPEN = "<RootLayout {...currentRootLayoutProps}>\n"
SHELL_ROOT_CLOSE = "\n</RootLayout>"
# The {#if CurrentResourceLayout} branch is always emitted once a route has
# ANY layout, even if this specific route has no resource layout at build
# time -- soft-nav can swap one in later, and the shell's markup shape can't
# change after hydration. Both branches render the leaf via {@render
# leafSlot()} so a route with no resource layout (the common root-only case)
# still renders its leaf instead of silently disappearing.
SHELL_RESOURCE_BLOCK = """{#if CurrentResourceLayout}
  <CurrentResourceLayout {...currentResourceLayoutProps}>
    {@render leafSlot()}
  </CurrentResourceLayout>
{:else}
  {@render leafSlot()}
{/if}
"""


CLIENT_BOOTSTRAP_WITH_SHELL_TEMPLATE = """\
import {{ hydrate }} from 'svelte';
import {{ stringify, parse }} from 'devalue';
import {{ seedRoute, applyRouteNav }} from '$route';
import {{ __setIdentity as __fymoSetIdentity }} from '$auth';
import Shell from './{shell_filename}';
import InitialLeaf from '{component_import}';
{initial_resource_layout_import}

// Re-export the route's leaf Svelte component so the soft-nav router can
// dynamic-`import()` this bundle later and pluck `.default` without
// re-running the boot logic below (same contract as CLIENT_ENTRY_TEMPLATE).
export default InitialLeaf;

if (typeof window !== 'undefined' && !window.__fymoBooted) {{
window.__fymoBooted = true;

const propsEl = document.getElementById('svelte-props');
const initialProps = propsEl ? JSON.parse(propsEl.textContent) : {{ leafProps: {{}}, layoutProps: {{ root: {{}}, resource: {{}} }} }};
const docEl = document.getElementById('svelte-doc');
let currentDoc = docEl ? JSON.parse(docEl.textContent) : {{}};
globalThis.getDoc = () => currentDoc;

// Seed the $auth identity store from the SSR payload before
// hydrate(), so the first client render agrees with the server's.
const identityEl = document.getElementById('fymo-identity');
__fymoSetIdentity(identityEl ? JSON.parse(identityEl.textContent) : null);

// Seed the reactive route state from this request's own URL + the server's
// resolved :id-style params, before hydrate() -- so the first subscriber
// that reads it after mount already sees the right value.
seedRoute();

{b64url}
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
    {error_throw}
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
__resolveRemoteProps(initialProps.leafProps);
__resolveRemoteProps(initialProps.layoutProps.root);
__resolveRemoteProps(initialProps.layoutProps.resource);

const target = document.getElementById('svelte-app');
const shellInstance = hydrate(Shell, {{
    target,
    props: {{
        leafProps: initialProps.leafProps,
        layoutProps: initialProps.layoutProps,
        initialLeaf: InitialLeaf,
        initialResourceLayout: {initial_resource_layout_value},
    }},
}});
let currentResourceLayoutId = {initial_resource_layout_id};

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

let inflight = null;
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
    if (env.type === 'redirect') {{ window.location.href = env.location; return; }}
    if (env.type === 'error') {{ window.location.href = path; return; }}
    inflight = null;

    const data = parse(env.result);
    __fymoSetIdentity(data.identity ?? null);
    const leaf = data.leaf;

    // Routes that don't use the layout shell (uses_layout_shell=false in the
    // manifest, surfaced here as leaf.usesLayoutShell) are architecturally
    // incompatible with this shell instance's composed tree -- fall back to
    // a full browser navigation rather than trying to reconcile shapes.
    if (leaf.usesLayoutShell === false) {{
        window.location.href = path;
        return;
    }}

    const cssUrls = [...(leaf.css || []), ...(leaf.resourceLayout ? leaf.resourceLayout.css || [] : [])];
    if (cssUrls.length) {{
        try {{ await Promise.all(cssUrls.map(ensureCss)); }} catch (_) {{}}
    }}

    let leafMod;
    try {{ leafMod = await import(leaf.module); }}
    catch (e) {{ window.location.href = path; return; }}
    const NewLeaf = leafMod.default;
    if (!NewLeaf) {{ window.location.href = path; return; }}
    __resolveRemoteProps(leaf.props);
    shellInstance.swapLeaf(NewLeaf, leaf.props);

    const newResourceLayoutId = leaf.resourceLayout ? leaf.resourceLayout.id : null;
    if (newResourceLayoutId !== currentResourceLayoutId) {{
        if (leaf.resourceLayout) {{
            let layoutMod;
            try {{ layoutMod = await import(leaf.resourceLayout.module); }}
            catch (e) {{ window.location.href = path; return; }}
            __resolveRemoteProps(leaf.resourceLayout.props);
            shellInstance.swapResourceLayout(layoutMod.default, leaf.resourceLayout.props);
        }} else {{
            shellInstance.swapResourceLayout(null, {{}});
        }}
        currentResourceLayoutId = newResourceLayoutId;
    }} else if (leaf.resourceLayout) {{
        // Same resource layout id as before -- only its props need
        // refreshing (the layout controller re-runs every navigation, same
        // as any controller), not its component. Uses a dedicated
        // props-only export rather than overloading swapResourceLayout,
        // which would otherwise need a sentinel to mean "keep current
        // component, just update props."
        __resolveRemoteProps(leaf.resourceLayout.props);
        shellInstance.updateResourceLayoutProps(leaf.resourceLayout.props);
    }}

    if (leaf.rootLayoutProps) {{
        __resolveRemoteProps(leaf.rootLayoutProps);
        shellInstance.updateRootLayoutProps(leaf.rootLayoutProps);
    }}

    currentDoc = data.doc || {{}};
    applyRouteNav(path, data.params);
    if (data.title) document.title = data.title;
    if (push) history.pushState({{ path }}, '', path);
    window.scrollTo(0, 0);
    window.dispatchEvent(new CustomEvent('fymo:navigate', {{ detail: {{ path, leaf }} }}));
}}

const disabledMeta = document.querySelector('meta[name="fymo-disabled-resources"]');
const disabledResources = new Set(
    (disabledMeta && disabledMeta.getAttribute('content') || '')
        .split(',').map(s => s.trim()).filter(Boolean)
);

function isDisabledResource(pathname) {{
    if (disabledResources.size === 0) return false;
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


def _import_line(name: str, path: Path, out_dir_resolved: Path) -> str:
    rel = os.path.relpath(path, out_dir_resolved)
    module_path = rel.replace(os.sep, "/")
    if not module_path.startswith("."):
        module_path = "./" + module_path
    return f"import {name} from '{module_path}';"


def _shell_body(route: Route, out_dir_resolved: Path) -> str:
    """Build the source of a route's <name>.shell.svelte.

    The {#if CurrentResourceLayout}...{:else}...{/if} branch is always
    emitted once a route has ANY layout, even if this specific route
    currently has no resource layout -- soft-nav can take the user to a
    sibling route that does, and the shell's markup shape can't change
    after hydration.
    """
    has_root = any(ref.level == "root" for ref in route.layout_chain)
    has_resource = any(ref.level == "resource" for ref in route.layout_chain)

    imports = ["  " + _import_line("Leaf", route.entry_path, out_dir_resolved)]
    for ref in route.layout_chain:
        name = "RootLayout" if ref.level == "root" else "ResourceLayout"
        imports.append("  " + _import_line(name, ref.svelte_path, out_dir_resolved))
    if not has_resource:
        imports.append("  // No resource layout for this route at build time;")
        imports.append("  // CurrentResourceLayout may still be set reactively via soft-nav.")

    root_open = SHELL_ROOT_OPEN if has_root else ""
    root_close = SHELL_ROOT_CLOSE if has_root else ""

    return SHELL_TEMPLATE.format(
        imports="\n".join(imports),
        root_open=root_open,
        root_close=root_close,
        resource_block=SHELL_RESOURCE_BLOCK,
    )


def write_client_entries(
    routes: Iterable[Route],
    out_dir: Path,
    project_root: Path,
    dev: bool = False,
) -> Dict[str, Path]:
    """Write a client entry per route, returning {route_name: entry_path}.

    Routes with no layout_chain get the plain CLIENT_ENTRY_TEMPLATE,
    unchanged from before this feature existed. Routes with a layout_chain
    additionally get a '<name>.shell.svelte' sibling file and a bootstrap
    '<name>.client.js' that hydrates the shell and drives it reactively on
    soft-nav instead of unmounting/remounting.
    """
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

        if not route.layout_chain:
            body = CLIENT_ENTRY_TEMPLATE.format(
                component_import=component_import, b64url=B64URL_JS,
                error_throw=REMOTE_ERROR_THROW_JS,
            ) + sse_snippet
            entry_path = out_dir / f"{route.name}.client.js"
            entry_path.write_text(body)
            written[route.name] = entry_path
            continue

        shell_filename = f"{route.name}.shell.svelte"
        (out_dir / shell_filename).write_text(_shell_body(route, out_dir_resolved))

        has_resource = any(ref.level == "resource" for ref in route.layout_chain)
        initial_resource_layout_import = ""
        initial_resource_layout_value = "null"
        initial_resource_layout_id = "null"
        if has_resource:
            resource_ref = next(ref for ref in route.layout_chain if ref.level == "resource")
            initial_resource_layout_import = _import_line(
                "InitialResourceLayout", resource_ref.svelte_path, out_dir_resolved
            )
            initial_resource_layout_value = "InitialResourceLayout"
            initial_resource_layout_id = f"'{resource_ref.id}'"

        bootstrap = CLIENT_BOOTSTRAP_WITH_SHELL_TEMPLATE.format(
            shell_filename=shell_filename,
            component_import=component_import,
            initial_resource_layout_import=initial_resource_layout_import,
            initial_resource_layout_value=initial_resource_layout_value,
            initial_resource_layout_id=initial_resource_layout_id,
            b64url=B64URL_JS,
            error_throw=REMOTE_ERROR_THROW_JS,
        ) + sse_snippet
        entry_path = out_dir / f"{route.name}.client.js"
        entry_path.write_text(bootstrap)
        written[route.name] = entry_path
    return written
