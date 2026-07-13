"""Tests for per-gunicorn-worker Node sidecar isolation + graceful shutdown.

A forked gunicorn worker inheriting a shared Sidecar subprocess (via
os.fork()) would corrupt the length-prefixed stdio framing, since multiple
processes would read/write the same pipe. Each worker must own its own
`FymoApp` (and therefore its own Node child), built *after* fork via the
`post_fork` gunicorn hook, and reaped on `worker_exit`.
"""
import pytest


@pytest.mark.usefixtures("node_available")
def test_each_app_has_its_own_sidecar(example_app):
    """Two independently-constructed FymoApp instances never share a sidecar
    process, and shutdown() stops each one's Node child."""
    from fymo.build.pipeline import BuildPipeline
    from fymo import create_app

    BuildPipeline(project_root=example_app).build(dev=False)

    a, b = create_app(example_app), create_app(example_app)
    # Capture the Popen objects before shutdown: Sidecar.stop() clears
    # sidecar._proc to None once stopped, so poll() must be checked on the
    # reference we hold here, not on the (now-cleared) sidecar attribute.
    proc_a, proc_b = a.sidecar._proc, b.sidecar._proc
    try:
        assert proc_a.pid != proc_b.pid
    finally:
        a.shutdown()
        b.shutdown()
        assert proc_a.poll() is not None
        assert proc_b.poll() is not None


@pytest.mark.usefixtures("node_available")
def test_shutdown_is_idempotent(example_app):
    """Calling shutdown() twice must not raise (gunicorn worker_exit hooks and
    atexit/SIGTERM handlers can both fire for the same worker)."""
    from fymo.build.pipeline import BuildPipeline
    from fymo import create_app

    BuildPipeline(project_root=example_app).build(dev=False)

    app = create_app(example_app)
    app.shutdown()
    app.shutdown()  # must not raise


def test_worker_exit_hook_calls_shutdown_on_worker_app():
    """worker_exit(server, worker) must call shutdown() on the app instance
    that post_fork attached to this worker."""
    from fymo.server.gunicorn import _worker_exit

    calls = []

    class FakeApp:
        def shutdown(self):
            calls.append("shutdown")

    class FakeWorker:
        pass

    worker = FakeWorker()
    worker.app_instance = FakeApp()

    _worker_exit(server=None, worker=worker)

    assert calls == ["shutdown"]


def test_worker_exit_hook_is_noop_without_app_instance():
    """If post_fork never ran (or failed), worker_exit must not blow up."""
    from fymo.server.gunicorn import _worker_exit

    class FakeWorker:
        pass

    _worker_exit(server=None, worker=FakeWorker())  # must not raise


@pytest.mark.usefixtures("node_available")
def test_post_fork_builds_a_distinct_app_per_worker(example_app):
    """post_fork(server, worker) must construct a fresh FymoApp (own sidecar)
    for each worker, store it on worker.app_instance, and FymoGunicornApp.load()
    must dispatch to the most-recently-built worker app."""
    from fymo.build.pipeline import BuildPipeline
    from fymo import create_app
    from fymo.server.gunicorn import FymoGunicornApp, _post_fork

    BuildPipeline(project_root=example_app).build(dev=False)

    master_app = create_app(example_app)
    gunicorn_app = FymoGunicornApp(master_app, {"bind": "127.0.0.1:0", "workers": 2})

    class FakeServer:
        app = gunicorn_app

    class FakeWorker:
        pass

    w1, w2 = FakeWorker(), FakeWorker()
    try:
        _post_fork(FakeServer(), w1)
        _post_fork(FakeServer(), w2)

        assert w1.app_instance is not master_app
        assert w2.app_instance is not master_app
        assert w1.app_instance is not w2.app_instance
        assert w1.app_instance.sidecar._proc.pid != w2.app_instance.sidecar._proc.pid

        # load() is called once per worker process (preload_app=False), after
        # post_fork has already run in that same (forked) process — it must
        # serve the worker-owned app, not the pre-fork master instance.
        assert gunicorn_app.load() is w2.app_instance
    finally:
        w1.app_instance.shutdown()
        w2.app_instance.shutdown()
        master_app.shutdown()


@pytest.mark.usefixtures("node_available")
def test_run_prod_stops_master_sidecar_and_wires_hooks(example_app, monkeypatch):
    """run_prod must not let the pre-fork app's sidecar survive into workers,
    and must wire preload_app=False plus the post_fork/worker_exit hooks."""
    from fymo.build.pipeline import BuildPipeline
    from fymo import create_app
    from fymo.server import gunicorn as gunicorn_mod

    BuildPipeline(project_root=example_app).build(dev=False)

    app = create_app(example_app)
    master_proc = app.sidecar._proc

    captured = {}

    class FakeGunicornApp:
        def __init__(self, wsgi_app, options):
            captured["wsgi_app"] = wsgi_app
            captured["options"] = options

        def run(self):
            captured["ran"] = True

    monkeypatch.setattr(gunicorn_mod, "FymoGunicornApp", FakeGunicornApp)

    gunicorn_mod.run_prod(app, "127.0.0.1", 0, 2)

    assert captured["ran"] is True
    assert captured["options"]["preload_app"] is False
    assert captured["options"]["post_fork"] is gunicorn_mod._post_fork
    assert captured["options"]["worker_exit"] is gunicorn_mod._worker_exit
    # The master's own sidecar must already be stopped — it must never be
    # forked into a worker.
    assert master_proc.poll() is not None
