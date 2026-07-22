"""Real-browser-equivalent regression test for issue #42's `$route` store.

Building on the same jsdom-real-hydrate() approach as test_hydration_real.py:
this exists specifically because a `$state`-backed `.svelte.js` module (the
first implementation of this feature) looked correct by every static check --
built cleanly, resolved through esbuild, and even appeared exactly once in
the output -- but silently failed to propagate reactivity in a real browser.
esbuild had bundled two separate, disconnected copies of Svelte's internal
client runtime across two chunks; the mutated value was visible to any code
holding the object, but never reached a mounted component's `$effect`/
template. No test caught it because none of the existing coverage actually
drove a live navigation through a real hydrated component.

`route.js` (a plain `svelte/store` writable) is the fix. This test drives
the actual compiled artifact -- real esbuild output, real Svelte compiler
output, real hydrate() against real DOM APIs via jsdom -- and calls the
framework's own `applyRouteNav` (imported from the same resolved module
path a real soft-nav's boot code would import) to prove a mounted
component's reactive read of `$route` actually updates, not just that the
underlying store object's value changed.
"""
import json
import socket
import subprocess
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HYDRATION_CHECK_JS = REPO_ROOT / "fymo" / "build" / "js" / "hydration_check.mjs"

# Root layout stays mounted across every soft nav (only the leaf/resource
# layout swap) -- reading $route here, rather than in a leaf, is what
# actually exercises the "does a long-lived component see a later mutation"
# question the original bug was about.
_ROUTE_PROBE_LAYOUT = """<script>
  import { route, applyRouteNav } from '$route';
  if (typeof window !== 'undefined') window.__testApplyRouteNav = applyRouteNav;
  let { children } = $props();
</script>

<div id="route-probe">{$route.pathname} | {JSON.stringify($route.params)}</div>
{@render children()}
"""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_hydration_check_with_after_boot(url: str, dist_dir: Path, after_boot_js: str) -> dict:
    """Runs checkHydration with an inline `afterBoot` hook (see
    hydration_check.mjs) as a subprocess Node script, mirroring the
    existing inline-script pattern in test_hydration_real.py's
    reusable-across-calls test."""
    script = f"""
import {{ checkHydration }} from {json.dumps(str(HYDRATION_CHECK_JS))};

const result = await checkHydration(
  {json.dumps(url)},
  {json.dumps(str(dist_dir))},
  5000,
  {{ afterBoot: async (window) => {{
    {after_boot_js}
  }} }},
);
console.log(JSON.stringify(result));
"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        pytest.fail(f"node script failed.\nstdout: {proc.stdout}\nstderr: {proc.stderr}")
    lines = proc.stdout.strip().splitlines()
    if not lines:
        pytest.fail(f"node script produced no output.\nstderr: {proc.stderr}")
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        pytest.fail(f"node script produced non-JSON output.\nstdout: {proc.stdout}\nstderr: {proc.stderr}")


@pytest.mark.usefixtures("node_available")
def test_route_store_propagates_to_a_persistently_mounted_component(blog_app: Path, monkeypatch):
    """The regression test proper: call the framework's own applyRouteNav
    (not a hand-rolled stand-in) against a really-hydrated root layout, and
    assert the DOM -- not just the store's internal value -- updates."""
    (blog_app / "app" / "templates" / "_layout.svelte").write_text(_ROUTE_PROBE_LAYOUT)

    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=blog_app).build(dev=False)

    monkeypatch.chdir(blog_app)
    from fymo import create_app
    app = create_app(blog_app, dev=False)

    from fymo.server.dev import make_dev_server
    port = _free_port()
    server = make_dev_server("127.0.0.1", port, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        dist_dir = blog_app / "dist"

        # Sanity check: the initial, un-navigated render already reflects
        # the real request's own URL (seedRoute(), proven separately by
        # test_entry_generator.py/test_html.py) -- confirm it end to end
        # too, so a regression in seeding doesn't hide behind this test's
        # main assertion (which is entirely about the *second* state).
        initial = _run_hydration_check_with_after_boot(
            f"http://127.0.0.1:{port}/",
            dist_dir,
            """
            const text = window.document.getElementById('route-probe').textContent;
            if (!text.includes('/') || !text.includes('{}')) {
              throw new Error('initial seed looked wrong: ' + text);
            }
            """,
        )
        assert initial["ok"] is True, initial
        assert initial["errors"] == [], initial

        # The actual regression check: mutate route state the same way a
        # real soft nav's boot code does, then read the DOM a mounted
        # component rendered from $route -- not the store's own value.
        result = _run_hydration_check_with_after_boot(
            f"http://127.0.0.1:{port}/",
            dist_dir,
            """
            window.__testApplyRouteNav('/posts/1', { id: '1' });
            await new Promise((r) => setTimeout(r, 100));
            const text = window.document.getElementById('route-probe').textContent;
            if (!text.includes('/posts/1')) {
              throw new Error('component did not react to the route mutation, saw: ' + text);
            }
            if (!text.includes('"id":"1"')) {
              throw new Error('params did not reach the component, saw: ' + text);
            }
            """,
        )
        assert result["ok"] is True, result
        assert result["errors"] == [], result
    finally:
        server.shutdown()
        thread.join(timeout=5)
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_client_bundle_does_not_duplicate_the_svelte_runtime(blog_app: Path):
    """Structural regression guard for the exact root cause: a $state
    proxy created in a compileModule()-processed .svelte.js file ended up
    in a chunk with its own fully inlined copy of svelte/internal/client
    (proxy.js, sources.js, runtime.js), disconnected from the copy every
    .svelte component's compiled output imports -- mutations were visible
    on the object but invisible to effects. route.js is a plain
    svelte/store module now (no special compilation), which should never
    trigger this esbuild code-splitting duplication again; assert it
    doesn't, independent of whether the propagation test above happens to
    catch a regression here some other way."""
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=blog_app).build(dev=False)

    # Source-path comments (`// node_modules/svelte/src/...`) don't survive
    # minification, so this can't key off them the way manual inspection
    # during debugging did -- Svelte's internal error-catalog message
    # (`state_proxy_equality_mismatch`, an svelte.dev/e/ doc-link id) is a
    # runtime string literal, not a comment, so it survives minification
    # and only exists inside the proxy-reactivity source Svelte itself
    # bundles. If it shows up in more than one chunk, the client runtime
    # got duplicated across an esbuild chunk boundary -- exactly the defect
    # that silently broke $route reactivity the first time.
    client_dir = blog_app / "dist" / "client"
    marker = "state_proxy_equality_mismatch"
    chunks_with_runtime_source = [
        f for f in client_dir.glob("*.js") if marker in f.read_text(errors="ignore")
    ]
    assert len(chunks_with_runtime_source) <= 1, (
        "svelte's internal client runtime appears bundled into more than one "
        f"chunk, which is exactly the duplication that broke $route reactivity: "
        f"{[f.name for f in chunks_with_runtime_source]}"
    )
