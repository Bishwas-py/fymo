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
