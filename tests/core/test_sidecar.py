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


# ---------------- stdout collision (issue #84) ----------------


def _inject_console_line(example_app: Path, line: str) -> None:
    """Insert a statement at the top of the todos template's script block so it
    executes during every SSR render of the `todos` route."""
    template = example_app / "app" / "templates" / "todos" / "index.svelte"
    source = template.read_text()
    assert "<script>" in source
    template.write_text(source.replace("<script>", f"<script>\n  {line}", 1))


def _render_in_thread(sidecar: Sidecar, join_seconds: float):
    """Run one todos render on a worker thread and join with a bound, so a
    sidecar hang shows up as a failed assertion instead of freezing pytest."""
    import threading

    outcome = {}

    def work():
        try:
            outcome["result"] = sidecar.render(
                route="todos", props={"todos": [], "user": {}, "stats": {}}
            )
        except Exception as e:
            outcome["error"] = e

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(join_seconds)
    return t, outcome


@pytest.mark.usefixtures("node_available")
def test_console_log_during_render_does_not_hang(example_app: Path):
    """Issue #84: console.log in component code used to interleave text into
    the binary IPC stream and hang the request forever."""
    _inject_console_line(example_app, "console.log('stdout-collision-probe');")
    BuildPipeline(project_root=example_app).build(dev=False)
    sidecar = Sidecar(dist_dir=example_app / "dist", timeout=5.0)
    sidecar.start()
    try:
        t, outcome = _render_in_thread(sidecar, join_seconds=10.0)
        assert not t.is_alive(), "render hung: console.log corrupted the IPC stream"
        assert "error" not in outcome, outcome.get("error")
        assert "todo-app" in outcome["result"]["body"]

        # The same process must serve the next request: no corruption carryover.
        again = sidecar.render(route="todos", props={"todos": [], "user": {}, "stats": {}})
        assert "todo-app" in again["body"]
        assert sidecar._restart_count == 0
    finally:
        sidecar.stop()


@pytest.mark.usefixtures("node_available")
@pytest.mark.parametrize("method", ["info", "warn", "debug"])
def test_other_console_methods_do_not_hang(example_app: Path, method: str):
    _inject_console_line(example_app, f"console.{method}('probe-{method}');")
    BuildPipeline(project_root=example_app).build(dev=False)
    sidecar = Sidecar(dist_dir=example_app / "dist", timeout=5.0)
    sidecar.start()
    try:
        t, outcome = _render_in_thread(sidecar, join_seconds=10.0)
        assert not t.is_alive(), f"render hung on console.{method}"
        assert "todo-app" in outcome["result"]["body"]
    finally:
        sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_console_output_surfaces_on_stderr_prefixed(example_app: Path, capsys):
    """Redirected console output must be visible and attributable, not dropped."""
    import time

    _inject_console_line(example_app, "console.log('visible-probe-84');")
    BuildPipeline(project_root=example_app).build(dev=False)
    sidecar = Sidecar(dist_dir=example_app / "dist", timeout=5.0)
    sidecar.start()
    try:
        sidecar.render(route="todos", props={"todos": [], "user": {}, "stats": {}})
        # The pump thread forwards asynchronously; poll briefly.
        deadline = time.monotonic() + 3.0
        err = ""
        while time.monotonic() < deadline:
            err += capsys.readouterr().err
            if "visible-probe-84" in err:
                break
            time.sleep(0.05)
        assert "[sidecar] visible-probe-84" in err
    finally:
        sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_high_volume_console_logging_does_not_deadlock(example_app: Path):
    """Logging beyond the OS pipe buffer (~64KB) must not wedge Node mid-write."""
    _inject_console_line(
        example_app,
        "for (let i = 0; i < 200; i++) console.log('x'.repeat(1024));",
    )
    BuildPipeline(project_root=example_app).build(dev=False)
    sidecar = Sidecar(dist_dir=example_app / "dist", timeout=10.0)
    sidecar.start()
    try:
        t, outcome = _render_in_thread(sidecar, join_seconds=15.0)
        assert not t.is_alive(), "render hung: stderr pipe buffer filled without a reader"
        assert "todo-app" in outcome["result"]["body"]
    finally:
        sidecar.stop()


def test_garbage_on_stdout_fails_bounded_not_forever(tmp_path: Path):
    """Any non-frame bytes on the IPC stream (this bug or a future one) must
    produce a bounded SidecarError, never an indefinite hang. The old code's
    select() only guarded time-to-first-byte; garbage arrives instantly and
    then the frame read blocked forever."""
    import time

    bad_dir = tmp_path / "dist"
    bad_dir.mkdir()
    (bad_dir / "sidecar.mjs").write_text(
        "process.stdin.on('data', () => {\n"
        "  process.stdout.write('this is not a frame and never will be\\n');\n"
        "});\n"
        "setInterval(() => {}, 1000);\n"
    )
    sidecar = Sidecar(dist_dir=bad_dir, timeout=0.5)
    sidecar.start()
    try:
        start = time.monotonic()
        with pytest.raises(SidecarError, match="IPC failed"):
            sidecar.render(route="anything", props={})
        elapsed = time.monotonic() - start
        # One attempt + one retry, each bounded by the 0.5s deadline, plus
        # process spawn overhead. Generous bound; the point is "not forever".
        assert elapsed < 5.0, f"desynced stream took {elapsed:.1f}s to fail"
        # A desynced process must not be reused: the failure path killed it.
        assert sidecar._restart_count >= 1
    finally:
        sidecar.stop()


def test_slow_but_valid_frame_within_deadline_succeeds(tmp_path: Path):
    """The deadline bounds the whole frame, but a legitimately slow trickle
    that completes in time must not be cut off by any per-read impatience."""
    slow_dir = tmp_path / "dist"
    slow_dir.mkdir()
    (slow_dir / "sidecar.mjs").write_text(
        "let buf = Buffer.alloc(0);\n"
        "process.stdin.on('data', (c) => {\n"
        "  buf = Buffer.concat([buf, c]);\n"
        "  if (buf.length < 4) return;\n"
        "  const body = Buffer.from(JSON.stringify({ id: 1, ok: true, body: 'slow', head: '' }));\n"
        "  const len = Buffer.alloc(4);\n"
        "  len.writeUInt32BE(body.length, 0);\n"
        "  process.stdout.write(len);\n"
        "  setTimeout(() => process.stdout.write(body.subarray(0, 5)), 300);\n"
        "  setTimeout(() => process.stdout.write(body.subarray(5)), 600);\n"
        "  buf = Buffer.alloc(0);\n"
        "});\n"
        "setInterval(() => {}, 1000);\n"
    )
    sidecar = Sidecar(dist_dir=slow_dir, timeout=5.0)
    sidecar.start()
    try:
        result = sidecar.render(route="anything", props={})
        assert result["body"] == "slow"
    finally:
        sidecar.stop()
