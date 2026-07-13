"""Real-hydration regression test.

Builds blog_app for real, serves it on a real TCP port, and runs the actual
compiled client bundle against the actual SSR HTML via hydration_check.mjs
(fymo/build/js/hydration_check.mjs) -- a small jsdom-based script that
executes Svelte's real hydrate() call against real DOM APIs, the same way a
real browser would.

This exists because every hydration bug found in this codebase so far (the
dev_orchestrator layout-fields bug, and the SSR/shell static-vs-dynamic
component-tag bug -- see composition_generator.py's SSR_TREE_TEMPLATE) was
invisible to the rest of the test suite: everything else talks to the WSGI
app in-process and asserts on HTML strings or manifest fields, which proves
the server produced *some* markup but proves nothing about whether a
browser can actually hydrate it. This test closes that blind spot without
depending on a full browser-automation stack (Playwright et al.).
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


def _run_hydration_check(url: str, dist_dir: Path) -> dict:
    proc = subprocess.run(
        ["node", str(HYDRATION_CHECK_JS), url, str(dist_dir)],
        capture_output=True, text=True, timeout=30,
    )
    lines = proc.stdout.strip().splitlines()
    if not lines:
        pytest.fail(f"hydration_check.mjs produced no output.\nstderr: {proc.stderr}")
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        pytest.fail(f"hydration_check.mjs produced non-JSON output.\nstdout: {proc.stdout}\nstderr: {proc.stderr}")


@pytest.mark.usefixtures("node_available")
def test_layout_shell_routes_hydrate_cleanly(blog_app: Path, monkeypatch):
    """Both the root-layout-only "index" route and the "posts"
    resource-detail route -- the two routes actually affected by the
    SSR/shell dynamic-component-tag mismatch -- must hydrate with zero
    console errors/warnings against a real, freshly-built app."""
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=blog_app).build(dev=False)

    monkeypatch.chdir(blog_app)
    from tests.integration._seed_helpers import seed_test_post
    seed_test_post()

    from fymo import create_app
    app = create_app(blog_app, dev=False)

    from fymo.server.dev import make_dev_server
    port = _free_port()
    server = make_dev_server("127.0.0.1", port, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        dist_dir = blog_app / "dist"
        for route_path in ("/", "/posts/welcome-to-fymo"):
            result = _run_hydration_check(f"http://127.0.0.1:{port}{route_path}", dist_dir)
            assert result["errors"] == [], f"{route_path}: {result}"
            assert result["warnings"] == [], f"{route_path}: {result}"
            assert result["ok"] is True, f"{route_path}: {result}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_hydration_check_reusable_across_calls_in_one_process(blog_app: Path, monkeypatch):
    """hydration_check.mjs's `checkHydration` is also importable as a
    library function (not just a one-shot CLI), for callers that want to
    check more than one route without a subprocess per route. Prove that
    calling it twice in the same Node process doesn't leak state: it
    globally overrides Node's own `Event`/`EventTarget` classes with
    jsdom's (so `instanceof` checks against jsdom-created DOM objects work
    -- Node has its own separate, non-DOM implementations of those same
    names), which MUST be restored after each call or the second call (or
    anything else sharing that process) would silently corrupt every
    `instanceof Event`/`EventTarget` check for the rest of the process."""
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=blog_app).build(dev=False)

    monkeypatch.chdir(blog_app)
    from tests.integration._seed_helpers import seed_test_post
    seed_test_post()

    from fymo import create_app
    app = create_app(blog_app, dev=False)

    from fymo.server.dev import make_dev_server
    port = _free_port()
    server = make_dev_server("127.0.0.1", port, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        dist_dir = blog_app / "dist"
        script = f"""
import {{ checkHydration }} from {json.dumps(str(HYDRATION_CHECK_JS))};

const nodeEventBefore = globalThis.Event;
const nodeEventTargetBefore = globalThis.EventTarget;

const r1 = await checkHydration({json.dumps(f"http://127.0.0.1:{port}/")}, {json.dumps(str(dist_dir))});
const eventRestoredAfterRun1 = globalThis.Event === nodeEventBefore;
const eventTargetRestoredAfterRun1 = globalThis.EventTarget === nodeEventTargetBefore;

const r2 = await checkHydration({json.dumps(f"http://127.0.0.1:{port}/posts/welcome-to-fymo")}, {json.dumps(str(dist_dir))});
const eventRestoredAfterRun2 = globalThis.Event === nodeEventBefore;
const eventTargetRestoredAfterRun2 = globalThis.EventTarget === nodeEventTargetBefore;

console.log(JSON.stringify({{
  r1, r2,
  eventRestoredAfterRun1, eventTargetRestoredAfterRun1,
  eventRestoredAfterRun2, eventTargetRestoredAfterRun2,
  errorArraysAreDistinctObjects: r1.errors !== r2.errors,
}}));
"""
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0, f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        result = json.loads(proc.stdout.strip().splitlines()[-1])

        assert result["r1"]["ok"] is True, result["r1"]
        assert result["r2"]["ok"] is True, result["r2"]
        assert result["eventRestoredAfterRun1"] is True
        assert result["eventTargetRestoredAfterRun1"] is True
        assert result["eventRestoredAfterRun2"] is True
        assert result["eventTargetRestoredAfterRun2"] is True
        assert result["errorArraysAreDistinctObjects"] is True
    finally:
        server.shutdown()
        thread.join(timeout=5)
        if app.sidecar:
            app.sidecar.stop()
