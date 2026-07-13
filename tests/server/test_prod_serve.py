"""Tests for the production server mode (`fymo serve --prod`)."""
import fymo.cli.commands.serve as serve_mod


def test_gunicorn_app_config_from_args(tmp_path):
    from fymo.server.gunicorn import FymoGunicornApp

    app = FymoGunicornApp(wsgi_app=lambda e, s: [b""], options={"bind": "0.0.0.0:9000", "workers": 3})
    app.load_config()

    assert app.cfg.bind == ["0.0.0.0:9000"]
    assert app.cfg.workers == 3
    assert app.cfg.worker_class_str == "sync"


def test_run_server_prod_dispatches_to_run_prod(tmp_path, monkeypatch):
    """`run_server(..., prod=True)` should hand off to fymo.server.gunicorn.run_prod
    instead of starting the wsgiref dev server."""
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

    serve_mod.run_server(host="127.0.0.1", port=8123, reload=False, prod=True, workers=5)

    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8123
    assert calls["workers"] == 5
    assert callable(calls["wsgi_app"])
