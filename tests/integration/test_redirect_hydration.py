"""End-to-end proof that a remote function raising `fymo.remote.Redirect`
actually navigates the browser, not just that the server produced the right
JSON envelope -- see issue #58.

Builds blog_app for real, serves it on a real TCP port, and drives the real
compiled client bundle through jsdom's real hydrate() (fymo/build/js/
hydration_check.mjs, same tool tests/integration/test_hydration_real.py
uses), then clicks the `#go-to-login` button wired to blog_app's
`app/remote/redirect_demo.go_to_login` remote function. That function
unconditionally raises Redirect("/login"), so a real click round-trips
through: the real Svelte click handler -> the real generated `__rpc` (the
exact code at fymo/build/entry_generator.py's `if (env.type === 'redirect')`
branch) -> a real fetch to the real running WSGI app -> fymo's remote router
catching Redirect -> the real {"type": "redirect", "location": "/login", ...}
JSON -> back into `__rpc`, which must then set `window.location.href`.

jsdom does not implement real navigation (`window.location.href = ...`
silently no-ops and logs "Not implemented: navigation to another Document"
instead of taking effect -- this is a known, permanent jsdom limitation, not
a fymo bug), so asserting on the real `window.location.href` after the click
is not possible here. Instead, `afterBoot` temporarily substitutes
`globalThis.window` for a shallow object that inherits everything from the
real jsdom window except `location`, which is replaced with a plain
recordable stub -- the bundle's `window.location.href = env.location`
assignment then lands on that stub instead of jsdom's real (inert) Location
object, capturing exactly what the generated code attempted to do without
needing jsdom to actually support navigation. Node's own `fetch` also
doesn't know the page's origin the way a real browser's does, so relative
URLs (`/_fymo/remote/...`) are also resolved against the real server's
origin for the duration of the click.
"""
import json
import socket
import subprocess
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HYDRATION_CHECK_JS = REPO_ROOT / "fymo" / "build" / "js" / "hydration_check.mjs"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.usefixtures("node_available")
def test_remote_function_redirect_navigates_through_real_client_bundle(blog_app: Path, monkeypatch):
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=blog_app).build(dev=False)

    monkeypatch.chdir(blog_app)
    from fymo import create_app
    app = create_app(blog_app, dev=True)

    from fymo.server.dev import make_dev_server
    port = _free_port()
    server = make_dev_server("127.0.0.1", port, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{port}/redirect_demo"
        dist_dir = blog_app / "dist"
        script = f"""
import {{ checkHydration }} from {json.dumps(str(HYDRATION_CHECK_JS))};

const url = {json.dumps(url)};
let capturedHref = null;
let clickError = null;

const result = await checkHydration(url, {json.dumps(str(dist_dir))}, 5000, {{
  afterBoot: async (window) => {{
    // Substitute window.location for a recordable stub -- see this file's
    // module docstring for why jsdom's real Location can't be observed.
    const fakeLocation = {{ href: null }};
    const originalWindow = globalThis.window;
    globalThis.window = Object.create(originalWindow, {{
      location: {{ value: fakeLocation, configurable: true }},
    }});
    // Node's fetch has no page origin to resolve relative URLs against
    // (unlike a real browser) -- give it the real server's origin.
    const origin = new URL(url).origin;
    const realFetch = globalThis.fetch;
    globalThis.fetch = (input, init) => {{
      if (typeof input === 'string' && input.startsWith('/')) input = origin + input;
      return realFetch(input, init);
    }};
    try {{
      const btn = window.document.getElementById('go-to-login');
      if (!btn) throw new Error('button #go-to-login not found in rendered page');
      btn.click();
      const deadline = Date.now() + 3000;
      while (fakeLocation.href === null && Date.now() < deadline) {{
        await new Promise((r) => setTimeout(r, 25));
      }}
      capturedHref = fakeLocation.href;
    }} catch (e) {{
      clickError = e && (e.stack || e.message || String(e));
    }} finally {{
      globalThis.window = originalWindow;
      globalThis.fetch = realFetch;
    }}
  }},
}});

console.log(JSON.stringify({{ result, capturedHref, clickError }}));
"""
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0, f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        outcome = json.loads(proc.stdout.strip().splitlines()[-1])

        assert outcome["clickError"] is None, outcome
        assert outcome["result"]["errors"] == [], outcome["result"]
        assert outcome["result"]["ok"] is True, outcome["result"]
        # The real proof: the client's `if (env.type === 'redirect')` branch
        # (entry_generator.py:47) executed and attempted to navigate to
        # exactly the location the server's Redirect("/login") carried.
        assert outcome["capturedHref"] == "/login", outcome
    finally:
        server.shutdown()
        thread.join(timeout=5)
        if app.sidecar:
            app.sidecar.stop()
