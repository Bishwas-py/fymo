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
