"""Tests for the production server mode (`fymo serve --prod`)."""
import sys

import fymo.cli.commands.serve as serve_mod


def test_gunicorn_app_config_from_args(tmp_path):
    from fymo.server.gunicorn import FymoGunicornApp

    app = FymoGunicornApp(wsgi_app=lambda e, s: [b""], options={"bind": "0.0.0.0:9000", "workers": 3})
    app.load_config()

    assert app.cfg.bind == ["0.0.0.0:9000"]
    assert app.cfg.workers == 3
    assert app.cfg.worker_class_str == "sync"


def test_run_server_prod_dispatches_to_run_prod(tmp_path, monkeypatch):
    """`run_server(..., prod=True, server="gunicorn")` should hand off to
    fymo.server.gunicorn.run_prod instead of starting the wsgiref dev server.
    Pinned to the explicit gunicorn choice: the test venv has granian
    installed, so the default `server="auto"` would resolve to granian
    (issue #39) and boot a real server here."""
    project_dir = tmp_path / "myproj"
    project_dir.mkdir()
    (project_dir / "server.py").write_text(
        "def app(environ, start_response):\n"
        "    start_response('200 OK', [])\n"
        "    return [b'']\n"
    )
    monkeypatch.chdir(project_dir)

    calls = {}

    def fake_run_prod(wsgi_app, host, port, workers):
        calls["wsgi_app"] = wsgi_app
        calls["host"] = host
        calls["port"] = port
        calls["workers"] = workers

    monkeypatch.setattr(serve_mod, "run_prod", fake_run_prod)

    serve_mod.run_server(host="127.0.0.1", port=8123, prod=True, workers=5, server="gunicorn")

    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8123
    assert calls["workers"] == 5
    assert callable(calls["wsgi_app"])


class _FakeSidecar:
    """Stand-in for fymo.core.sidecar.Sidecar so FymoApp construction
    doesn't need to spawn a real Node process for this CLI-level test."""

    def __init__(self, dist_dir, timeout=30.0):
        self.dist_dir = dist_dir

    def start(self):
        pass

    def stop(self):
        pass

    def ping(self):
        return True


def test_run_server_prod_forces_dev_false_despite_stray_env(tmp_path, monkeypatch):
    """Issue #26: a stray FYMO_DEV=1 left exported in the shell must not be
    able to boot production in dev mode. `--prod` forces dev off *before*
    server.py is imported -- not just at some point before run_server
    returns -- so server.py's own `create_app(PROJECT_ROOT)` call (which
    reads FYMO_DEV the same way a real scaffolded server.py does) resolves
    dev=False too, not just the env var's final state. Pinned to the
    explicit gunicorn choice, same reason as the dispatch test above."""
    project_dir = tmp_path / "myproj"
    project_dir.mkdir()
    (project_dir / "dist" / "sidecar.mjs").parent.mkdir(parents=True, exist_ok=True)
    (project_dir / "dist" / "sidecar.mjs").write_text("// stub, never actually spawned in this test\n")
    (project_dir / "server.py").write_text(
        "from pathlib import Path\n"
        "from fymo import create_app\n"
        "PROJECT_ROOT = Path(__file__).resolve().parent\n"
        "app = create_app(PROJECT_ROOT)\n"
    )
    monkeypatch.chdir(project_dir)
    monkeypatch.setenv("FYMO_DEV", "1")
    monkeypatch.delitem(sys.modules, "server", raising=False)
    monkeypatch.setattr("fymo.core.sidecar.Sidecar", _FakeSidecar)

    calls = {}
    monkeypatch.setattr(
        serve_mod, "run_prod",
        lambda wsgi_app, host, port, workers: calls.__setitem__("wsgi_app", wsgi_app),
    )

    try:
        serve_mod.run_server(host="127.0.0.1", port=8123, prod=True, workers=2, server="gunicorn")
        assert calls["wsgi_app"].dev is False
    finally:
        sys.modules.pop("server", None)


def test_run_server_without_prod_delegates_to_run_dev(tmp_path, monkeypatch):
    """Issue #26: bare `fymo serve` (no --prod) is now a straight alias for
    `fymo dev`. The old path imported server.py and booted the wsgiref
    server directly against whatever dev value was already baked into the
    app object, with no watcher, no esbuild rebuild-on-save, no sidecar
    hot-reload -- effectively a worse `fymo dev`."""
    monkeypatch.chdir(tmp_path)

    import fymo.cli.commands.dev as dev_mod
    calls = {}

    def fake_run_dev(host, port):
        calls["host"] = host
        calls["port"] = port

    monkeypatch.setattr(dev_mod, "run_dev", fake_run_dev)

    serve_mod.run_server(host="0.0.0.0", port=9001, prod=False)

    assert calls == {"host": "0.0.0.0", "port": 9001}


def test_prod_default_without_granian_is_todays_gunicorn_path(tmp_path, monkeypatch):
    """Zero-behavior-change contract for issue #39: a deployment that passes
    no --server flag and has no granian installed must get exactly today's
    gunicorn path (server.py imported in the parent, run_prod invoked with
    the app object), not an error and not a different server."""
    project_dir = tmp_path / "myproj"
    project_dir.mkdir()
    (project_dir / "server.py").write_text(
        "def app(environ, start_response):\n"
        "    start_response('200 OK', [])\n"
        "    return [b'']\n"
    )
    monkeypatch.chdir(project_dir)
    monkeypatch.setattr(serve_mod, "_granian_available", lambda: False)
    monkeypatch.delitem(sys.modules, "server", raising=False)

    calls = {}

    def fake_run_prod(wsgi_app, host, port, workers):
        calls["wsgi_app"] = wsgi_app
        calls["host"] = host
        calls["port"] = port
        calls["workers"] = workers

    monkeypatch.setattr(serve_mod, "run_prod", fake_run_prod)

    try:
        serve_mod.run_server(host="127.0.0.1", port=8123, prod=True, workers=5)
    finally:
        sys.modules.pop("server", None)

    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8123
    assert calls["workers"] == 5
    assert callable(calls["wsgi_app"])
