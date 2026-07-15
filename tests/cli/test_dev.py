"""Tests for `fymo dev` explicitly enabling dev mode (issue #26).

`run_dev()` used to build the app with `create_app(project_root)` and no
`dev` kwarg, relying on the `FYMO_DEV` env var, which it never set itself.
Running `fymo dev` without separately exporting `FYMO_DEV=1` silently left
the app in production mode: no tracebacks on 500s, secure-only cookies,
full rate limiting.
"""
import os

import pytest

import fymo.cli.commands.dev as dev_mod


@pytest.fixture(autouse=True)
def _restore_fymo_dev_env():
    """run_dev() sets os.environ["FYMO_DEV"] directly (by design -- a real
    `fymo dev` process wants that var visible to anything it spawns), not
    through monkeypatch. monkeypatch.delenv on an already-absent key
    registers no undo, so without this fixture that mutation survives past
    the test and leaks FYMO_DEV=1 into every later test in the same pytest
    process -- silently flipping unrelated dev=None call sites (rate
    limiting, HSTS) into dev mode. Snapshot and restore regardless of what
    the code under test does to the var."""
    original = os.environ.get("FYMO_DEV")
    yield
    if original is None:
        os.environ.pop("FYMO_DEV", None)
    else:
        os.environ["FYMO_DEV"] = original


class _FakeOrchestrator:
    def __init__(self, project_root):
        self.project_root = project_root
        self.listeners = []

    def start(self):
        manifest = self.project_root / "dist" / "manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("{}")

    def stop(self):
        pass

    def add_listener(self, fn):
        self.listeners.append(fn)


class _FakeServer:
    def serve_forever(self):
        raise KeyboardInterrupt


class _FakeApp:
    sidecar = None


def test_run_dev_sets_fymo_dev_env_var(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FYMO_DEV", raising=False)
    monkeypatch.setattr(dev_mod, "DevOrchestrator", _FakeOrchestrator)
    monkeypatch.setattr("fymo.create_app", lambda project_root, dev=None: _FakeApp())
    monkeypatch.setattr("fymo.server.dev.make_dev_server", lambda host, port, app: _FakeServer())

    dev_mod.run_dev(host="127.0.0.1", port=8000)

    assert os.environ.get("FYMO_DEV") == "1"


def test_run_dev_passes_dev_true_explicitly_to_create_app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FYMO_DEV", raising=False)
    monkeypatch.setattr(dev_mod, "DevOrchestrator", _FakeOrchestrator)

    calls = {}

    def fake_create_app(project_root, dev=None):
        calls["project_root"] = project_root
        calls["dev"] = dev
        return _FakeApp()

    monkeypatch.setattr("fymo.create_app", fake_create_app)
    monkeypatch.setattr("fymo.server.dev.make_dev_server", lambda host, port, app: _FakeServer())

    dev_mod.run_dev(host="127.0.0.1", port=8000)

    assert calls["dev"] is True
    assert calls["project_root"] == tmp_path
