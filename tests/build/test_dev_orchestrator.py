"""DevOrchestrator.start() must apply the same directory-hygiene check as
BuildPipeline.build() -- `fymo dev` reads the live source tree just like
`fymo build` does, so a misplaced file should be caught there too."""
import json
import time
from pathlib import Path

import pytest

from fymo.build.dev_orchestrator import DevOrchestrator
from fymo.build.manifest import Manifest, LayoutRefAsset, RouteAssets


def test_start_fails_on_svelte_file_in_controllers(example_app: Path):
    (example_app / "app" / "controllers" / "oops.svelte").write_text("<div></div>")
    with pytest.raises(RuntimeError, match="app/controllers/oops.svelte"):
        DevOrchestrator(example_app).start()


def test_start_fails_on_py_file_in_components(example_app: Path):
    (example_app / "app" / "components").mkdir(parents=True, exist_ok=True)
    (example_app / "app" / "components" / "oops.py").write_text("x = 1\n")
    with pytest.raises(RuntimeError, match="app/components/oops.py"):
        DevOrchestrator(example_app).start()


def test_hygiene_check_runs_even_without_node_on_path(example_app: Path, monkeypatch):
    """Same ordering rationale as the BuildPipeline test: a pure filesystem
    check shouldn't be masked by (or wait on) the node-availability check."""
    (example_app / "app" / "controllers" / "oops.svelte").write_text("<div></div>")
    monkeypatch.setattr("fymo.build.prepare.shutil.which", lambda cmd: None)
    with pytest.raises(RuntimeError, match="app/controllers/oops.svelte"):
        DevOrchestrator(example_app).start()


def test_start_warns_but_succeeds_on_py_file_in_lib(example_app: Path, node_available, capsys):
    """Locked decision: app/lib/ is a warning, not a build failure. start()
    must not raise, unlike the hard-error cases above."""
    (example_app / "app" / "lib").mkdir(parents=True, exist_ok=True)
    (example_app / "app" / "lib" / "oops.py").write_text("x = 1\n")
    orch = DevOrchestrator(example_app)
    try:
        orch.start()
    finally:
        orch.stop()
    out = capsys.readouterr().out
    assert "app/lib/oops.py" in out
    assert "app/support" in out


def test_write_manifest_populates_layout_fields_from_synthetic_metafile(example_app: Path):
    """Fast, no real esbuild: proves _write_manifest()'s wiring to
    match_esbuild_outputs() is correct, independent of a real subprocess
    build. (The real end-to-end test below is what actually would have
    caught the original bug -- this one guards the wiring specifically.)"""
    orch = DevOrchestrator(example_app)
    orch._routes = [
        type("R", (), {
            "name": "home",
            "layout_chain": [type("Ref", (), {"level": "root", "id": "_root", "controller_module": None})()],
        })(),
    ]
    orch._all_layouts = [
        type("Ref", (), {"id": "_root", "svelte_path": example_app / "app" / "templates" / "_layout.svelte"})(),
    ]
    (example_app / "app" / "templates" / "_layout.svelte").write_text(
        "<script>\n  let { children } = $props();\n</script>\n{@render children()}\n"
    )
    orch._has_global_css = False
    orch._latest_metafile = {
        "outputs": {
            "dist/client/home.HASH1.js": {"entryPoint": "home.client.js"},
            "dist/client/_layout-_root.HASH2.js": {
                "entryPoint": str(example_app / "app" / "templates" / "_layout.svelte"),
            },
        }
    }
    orch._write_manifest()

    manifest = Manifest.read(example_app / "dist" / "manifest.json")
    assert manifest is not None
    assert manifest.routes["home"].uses_layout_shell is True
    assert manifest.routes["home"].layout_chain == [
        LayoutRefAsset(level="root", id="_root", controller_module=None)
    ]
    assert "_root" in manifest.layouts


def test_real_dev_session_resolves_route_runtime(blog_app: Path, node_available):
    """Issue #42's `$route` virtual import is wired into build.mjs's two
    esbuild passes AND separately into dev.mjs's -- two independent
    implementations, not a shared one (same drift shape journal_012 already
    flagged for the pre-esbuild pipeline). Wiring only one silently breaks
    every `fymo dev` build for any route, since the generated client entries
    always import '$route' regardless of dev/build mode. This is the guard
    for dev.mjs's copy specifically."""
    orch = DevOrchestrator(blog_app)
    try:
        orch.start()
        manifest_path = blog_app / "dist" / "manifest.json"
        deadline = time.time() + 30
        while time.time() < deadline and not manifest_path.exists():
            time.sleep(0.1)
        assert manifest_path.exists(), "dev build did not produce a manifest in 30s"

        client_dir = blog_app / "dist" / "client"
        deadline = time.time() + 10
        chunk_files = list(client_dir.glob("chunk-*.js"))
        while time.time() < deadline and not any("pathname" in f.read_text() for f in chunk_files):
            time.sleep(0.2)
            chunk_files = list(client_dir.glob("chunk-*.js"))
        assert any("pathname" in f.read_text() for f in chunk_files), (
            "no built chunk contains the route runtime's `pathname` state -- "
            "$route failed to resolve in dev mode"
        )
    finally:
        orch.stop()


def test_real_dev_session_writes_correct_layout_manifest(blog_app: Path, node_available):
    """End-to-end: the actual bug. Runs a real `fymo dev` session (via
    DevOrchestrator directly, not the CLI) against blog_app -- which has a
    real root _layout.svelte -- and confirms the manifest it writes has
    uses_layout_shell=True / a populated layout_chain, matching what
    BuildPipeline.build() would write for the exact same source tree.
    Before this fix, DevOrchestrator always wrote layout_chain=[] regardless
    of the real source, which is what caused the client bootstrap (which
    correctly saw the layout chain via entry_generator.py) to crash trying
    to read `.root` off undefined `layoutProps`."""
    orch = DevOrchestrator(blog_app)
    try:
        orch.start()
        manifest_path = blog_app / "dist" / "manifest.json"
        deadline = time.time() + 30
        while time.time() < deadline and not manifest_path.exists():
            time.sleep(0.1)
        assert manifest_path.exists(), "dev build did not produce a manifest in 30s"

        # Wait a little longer for the layout entry specifically -- routes
        # and layouts can land in different rebuild events.
        deadline = time.time() + 10
        manifest = Manifest.read(manifest_path)
        while time.time() < deadline and "_root" not in manifest.layouts:
            time.sleep(0.2)
            manifest = Manifest.read(manifest_path)

        assert manifest.routes["index"].uses_layout_shell is True
        assert any(ref.level == "root" and ref.id == "_root" for ref in manifest.routes["index"].layout_chain)
        assert manifest.routes["posts"].uses_layout_shell is True
        assert "_root" in manifest.layouts
    finally:
        orch.stop()
