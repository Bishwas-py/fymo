import os
import signal
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


@pytest.mark.usefixtures("node_available")
def test_auto_restarts_after_node_dies(example_app: Path):
    """Killing the Node child mid-session should be invisible to the next render."""
    BuildPipeline(project_root=example_app).build(dev=False)
    sidecar = Sidecar(dist_dir=example_app / "dist")
    sidecar.start()
    try:
        # First render establishes baseline.
        first = sidecar.render(route="todos", props={"todos": [], "user": {}, "stats": {}})
        assert "todo-app" in first["body"]
        old_pid = sidecar._proc.pid
        assert sidecar._restart_count == 0

        # Kill the child outside the sidecar's knowledge.
        os.kill(old_pid, signal.SIGKILL)
        sidecar._proc.wait(timeout=2)

        # Next render must transparently restart and succeed.
        second = sidecar.render(route="todos", props={"todos": [], "user": {}, "stats": {}})
        assert "todo-app" in second["body"]
        assert sidecar._proc is not None
        assert sidecar._proc.pid != old_pid
        assert sidecar._restart_count == 1
    finally:
        sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_send_after_explicit_stop_restarts(example_app: Path):
    """Calling render() after stop() should auto-start, not error."""
    BuildPipeline(project_root=example_app).build(dev=False)
    sidecar = Sidecar(dist_dir=example_app / "dist")
    sidecar.start()
    sidecar.stop()
    try:
        result = sidecar.render(route="todos", props={"todos": [], "user": {}, "stats": {}})
        assert "todo-app" in result["body"]
    finally:
        sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_timeout_kills_hung_node_and_raises(tmp_path: Path):
    """A child that never replies should be killed by the watchdog and surface SidecarError."""
    # Hand-roll a tiny sidecar that ignores stdin entirely.
    hung_dir = tmp_path / "dist"
    hung_dir.mkdir()
    (hung_dir / "sidecar.mjs").write_text(
        "// Eat stdin without ever replying.\n"
        "process.stdin.on('data', () => {});\n"
        "setInterval(() => {}, 1000);\n"
    )
    sidecar = Sidecar(dist_dir=hung_dir, timeout=0.5)
    sidecar.start()
    try:
        with pytest.raises(SidecarError, match="IPC failed"):
            sidecar.render(route="anything", props={})
        # After timeout: the original child was killed, retry spawned a fresh
        # one that also timed out → final SidecarError. Two restarts total.
        assert sidecar._restart_count >= 1
    finally:
        sidecar.stop()
