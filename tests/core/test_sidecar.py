from pathlib import Path
import pytest
from fymo.build.pipeline import BuildPipeline
from fymo.core.sidecar import Sidecar, SidecarError


@pytest.mark.usefixtures("node_available")
def test_render_returns_body_and_head(example_app: Path):
    BuildPipeline(project_root=example_app).build(dev=False)
    sidecar = Sidecar(dist_dir=example_app / "dist")
    sidecar.start()
    try:
        result = sidecar.render(route="todos", props={"todos": [], "user": {"name": "Test"}, "stats": {}})
        assert "body" in result
        assert "head" in result
        assert isinstance(result["body"], str)
        assert "todo-app" in result["body"]
    finally:
        sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_render_propagates_errors(example_app: Path):
    BuildPipeline(project_root=example_app).build(dev=False)
    sidecar = Sidecar(dist_dir=example_app / "dist")
    sidecar.start()
    try:
        with pytest.raises(SidecarError):
            sidecar.render(route="nonexistent_route", props={})
    finally:
        sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_ping_warms_module_cache(example_app: Path):
    BuildPipeline(project_root=example_app).build(dev=False)
    sidecar = Sidecar(dist_dir=example_app / "dist")
    sidecar.start()
    try:
        assert sidecar.ping() is True
    finally:
        sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_render_passes_doc_to_getDoc(example_app: Path):
    BuildPipeline(project_root=example_app).build(dev=False)
    sidecar = Sidecar(dist_dir=example_app / "dist")
    sidecar.start()
    try:
        result = sidecar.render(
            route="todos",
            props={"todos": [], "user": {}, "stats": {}},
            doc={"title": "Hello From Doc"},
        )
        assert "Document Title: Hello From Doc" in result["body"]
    finally:
        sidecar.stop()
