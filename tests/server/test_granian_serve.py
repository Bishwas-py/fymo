"""Tests for granian as a `fymo serve --prod` server (issue #39).

Server resolution lives in fymo.cli.commands.serve; the launcher lives in
fymo.server.granian_server. The property these tests pin hardest: the fymo
CLI parent process must never import the project's server.py on the granian
path, because each granian worker imports the target string itself and
builds its own FymoApp (and Node sidecar). A parent-built app would spawn a
sidecar that nothing ever serves or stops.
"""
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import fymo.cli.commands.serve as serve_mod


def _scaffold_project(tmp_path, monkeypatch, server_py=None):
    project_dir = tmp_path / "myproj"
    project_dir.mkdir()
    (project_dir / "server.py").write_text(
        server_py
        if server_py is not None
        else (
            "def app(environ, start_response):\n"
            "    start_response('200 OK', [])\n"
            "    return [b'']\n"
        )
    )
    monkeypatch.chdir(project_dir)
    return project_dir


def _capture_granian(monkeypatch):
    import fymo.server.granian_server as granian_mod

    calls = {}

    def fake_run_prod_granian(project_root, host, port, workers):
        calls["project_root"] = project_root
        calls["host"] = host
        calls["port"] = port
        calls["workers"] = workers
        calls["fymo_dev_at_launch"] = os.environ.get("FYMO_DEV")

    monkeypatch.setattr(granian_mod, "run_prod_granian", fake_run_prod_granian)
    return calls


def _fail_run_prod(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("gunicorn run_prod must not be called on this path")

    monkeypatch.setattr(serve_mod, "run_prod", boom)


def test_auto_selects_granian_when_importable(tmp_path, monkeypatch, capsys):
    _scaffold_project(tmp_path, monkeypatch)
    monkeypatch.setattr(serve_mod, "_granian_available", lambda: True)
    _fail_run_prod(monkeypatch)
    calls = _capture_granian(monkeypatch)

    serve_mod.run_server(host="127.0.0.1", port=8123, prod=True, workers=3, server="auto")

    assert calls["project_root"] == Path.cwd()
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8123
    assert calls["workers"] == 3
    assert "granian" in capsys.readouterr().out


def test_auto_falls_back_to_gunicorn_when_granian_missing(tmp_path, monkeypatch, capsys):
    _scaffold_project(tmp_path, monkeypatch)
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
        serve_mod.run_server(host="127.0.0.1", port=8124, prod=True, workers=2, server="auto")
    finally:
        sys.modules.pop("server", None)

    assert calls["port"] == 8124
    assert calls["workers"] == 2
    assert callable(calls["wsgi_app"])
    # The fallback must be observable, never silent, and must name the extra.
    assert "fymo[granian]" in capsys.readouterr().out


def test_explicit_granian_missing_is_a_hard_error(tmp_path, monkeypatch, capsys):
    _scaffold_project(tmp_path, monkeypatch)
    monkeypatch.setattr(serve_mod, "_granian_available", lambda: False)
    _fail_run_prod(monkeypatch)

    with pytest.raises(SystemExit) as excinfo:
        serve_mod.run_server(host="127.0.0.1", port=8125, prod=True, workers=2, server="granian")

    assert excinfo.value.code not in (0, None)
    assert "pip install 'fymo[granian]'" in capsys.readouterr().out


def test_explicit_gunicorn_never_switches_to_granian(tmp_path, monkeypatch):
    _scaffold_project(tmp_path, monkeypatch)
    # Even with granian importable, an explicit gunicorn request stays gunicorn.
    monkeypatch.setattr(serve_mod, "_granian_available", lambda: True)
    monkeypatch.delitem(sys.modules, "server", raising=False)

    granian_calls = _capture_granian(monkeypatch)
    calls = {}
    monkeypatch.setattr(
        serve_mod, "run_prod",
        lambda wsgi_app, host, port, workers: calls.update(host=host, port=port, workers=workers),
    )

    try:
        serve_mod.run_server(host="127.0.0.1", port=8126, prod=True, workers=4, server="gunicorn")
    finally:
        sys.modules.pop("server", None)

    assert calls == {"host": "127.0.0.1", "port": 8126, "workers": 4}
    assert granian_calls == {}


def test_granian_parent_process_never_imports_server_py(tmp_path, monkeypatch):
    project_dir = _scaffold_project(
        tmp_path, monkeypatch,
        server_py="raise RuntimeError('server.py must never be imported by the CLI parent on the granian path')\n",
    )
    monkeypatch.setattr(serve_mod, "_granian_available", lambda: True)
    monkeypatch.delitem(sys.modules, "server", raising=False)
    calls = _capture_granian(monkeypatch)

    serve_mod.run_server(host="127.0.0.1", port=8127, prod=True, workers=1, server="granian")

    assert calls["project_root"] == Path.cwd()
    assert "server" not in sys.modules
    assert str(project_dir) not in sys.path
    assert str(Path.cwd()) not in sys.path


def test_granian_path_forces_fymo_dev_off(tmp_path, monkeypatch):
    _scaffold_project(tmp_path, monkeypatch)
    monkeypatch.setattr(serve_mod, "_granian_available", lambda: True)
    monkeypatch.setenv("FYMO_DEV", "1")
    calls = _capture_granian(monkeypatch)

    serve_mod.run_server(host="127.0.0.1", port=8128, prod=True, workers=1, server="granian")

    # granian workers inherit the parent's environment, so the stray-env
    # protection from issue #26 must land before the launcher is invoked.
    assert calls["fymo_dev_at_launch"] == "0"


def test_granian_missing_server_py_errors_before_resolution(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(serve_mod, "_granian_available", lambda: True)
    calls = _capture_granian(monkeypatch)

    serve_mod.run_server(host="127.0.0.1", port=8129, prod=True, workers=1, server="granian")

    assert calls == {}
    assert "server.py not found" in capsys.readouterr().out


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(url: str):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.status, resp.read()


@pytest.mark.usefixtures("node_available")
def test_granian_real_boot_serves_ssr_and_healthz(example_app):
    pytest.importorskip("granian")
    from fymo.build.pipeline import BuildPipeline

    BuildPipeline(project_root=example_app).build(dev=False)

    port = _free_port()
    script = (
        "from pathlib import Path\n"
        "from fymo.server.granian_server import run_prod_granian\n"
        f"run_prod_granian(Path.cwd(), '127.0.0.1', {port}, 1)\n"
    )
    env = dict(os.environ)
    env["FYMO_DEV"] = "0"
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=example_app,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 60
        last_err = None
        while True:
            if proc.poll() is not None:
                out = proc.stdout.read().decode(errors="replace")
                pytest.fail(f"granian exited early ({proc.returncode}):\n{out}")
            try:
                status, body = _get(f"http://127.0.0.1:{port}/")
                break
            except (urllib.error.URLError, ConnectionError, OSError) as e:
                last_err = e
                if time.monotonic() > deadline:
                    pytest.fail(f"granian never became reachable: {last_err}")
                time.sleep(0.25)

        assert status == 200
        assert b"todo-app" in body, "expected real SSR HTML from the todo_app home page"

        hz_status, hz_body = _get(f"http://127.0.0.1:{port}/healthz")
        assert hz_status == 200
        assert json.loads(hz_body)["status"] == "ok"
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
