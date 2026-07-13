import json
from pathlib import Path
import pytest
from fymo.build.pipeline import BuildPipeline, BuildError


@pytest.mark.usefixtures("node_available")
def test_build_produces_dist_for_example_app(example_app: Path):
    pipeline = BuildPipeline(project_root=example_app)
    result = pipeline.build(dev=False)

    assert result.ok
    assert (example_app / "dist" / "manifest.json").is_file()
    assert (example_app / "dist" / "ssr" / "todos.mjs").is_file()
    assert (example_app / "dist" / "sidecar.mjs").is_file()

    # at least one hashed client bundle
    client_files = list((example_app / "dist" / "client").glob("todos.*.js"))
    assert len(client_files) == 1


@pytest.mark.usefixtures("node_available")
def test_manifest_lists_each_route(example_app: Path):
    BuildPipeline(project_root=example_app).build(dev=False)
    manifest = json.loads((example_app / "dist" / "manifest.json").read_text())
    assert "todos" in manifest["routes"]
    todos = manifest["routes"]["todos"]
    assert todos["ssr"] == "ssr/todos.mjs"
    assert todos["client"].startswith("client/todos.")
    assert todos["client"].endswith(".js")


def test_build_fails_loudly_on_missing_node(example_app: Path, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(BuildError, match="node"):
        BuildPipeline(project_root=example_app).build(dev=False)


@pytest.mark.usefixtures("node_available")
def test_build_output_css_is_external_not_injected(example_app: Path):
    """Regression guard: if css defaults ever drift (Svelte/esbuild-svelte
    upstream change), a route's CSS must still land in a separate .css file,
    not get injected into the JS bundle at runtime."""
    from fymo.build.pipeline import BuildPipeline
    result = BuildPipeline(example_app).build(dev=False)
    from fymo.build.manifest import Manifest
    manifest = Manifest.read(result.manifest_path)
    home_css = manifest.routes["home"].css
    assert home_css is not None
    css_path = example_app / "dist" / home_css
    assert css_path.is_file()
    js_path = example_app / "dist" / manifest.routes["home"].client
    js_content = js_path.read_text()
    # Injected CSS would show up as a style-injection call in the JS bundle.
    assert "append_styles" not in js_content
