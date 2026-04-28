"""WSGI handler for remote function calls."""
import io
import json
import sys
from pathlib import Path
import pytest
from fymo.remote.router import handle_remote


def _scaffold(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path


def _call(environ: dict):
    responses = []
    def start_response(status, headers):
        responses.append((status, headers))
    body = b"".join(handle_remote(environ, start_response))
    return responses[0], body


def _make_environ(path: str, body: dict, cookies: str = "") -> dict:
    raw = json.dumps(body).encode()
    return {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(raw)),
        "CONTENT_TYPE": "application/json",
        "HTTP_COOKIE": cookies,
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(raw),
    }


@pytest.fixture
def remote_project(tmp_path: Path, monkeypatch):
    proj = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": (
            "from fymo.remote import current_uid, NotFound\n"
            "def hello(name: str) -> str:\n"
            "    return f'hi {name}'\n"
            "def whoami() -> str:\n"
            "    return current_uid()\n"
            "def boom() -> str:\n"
            "    raise NotFound('nope')\n"
        ),
    })
    monkeypatch.syspath_prepend(str(proj))
    yield proj
    for name in list(sys.modules):
        if name.startswith("app."):
            del sys.modules[name]


def test_calls_function_and_returns_data(remote_project):
    env = _make_environ("/__remote/posts/hello", {"args": ["alice"]})
    (status, headers), body = _call(env)
    assert status.startswith("200")
    payload = json.loads(body)
    assert payload == {"ok": True, "data": "hi alice"}


def test_issues_uid_on_first_call(remote_project):
    env = _make_environ("/__remote/posts/whoami", {"args": []})
    (status, headers), body = _call(env)
    assert status.startswith("200")
    set_cookie = next((v for k, v in headers if k.lower() == "set-cookie"), None)
    assert set_cookie is not None
    assert "fymo_uid=" in set_cookie
    payload = json.loads(body)
    assert payload["data"].startswith("u_")


def test_reads_existing_uid_cookie(remote_project):
    env = _make_environ("/__remote/posts/whoami", {"args": []}, cookies="fymo_uid=u_existing")
    (status, headers), body = _call(env)
    payload = json.loads(body)
    assert payload["data"] == "u_existing"


def test_unknown_function_returns_404(remote_project):
    env = _make_environ("/__remote/posts/nope", {"args": []})
    (status, headers), body = _call(env)
    assert status.startswith("404")


def test_validation_error_returns_422(remote_project):
    env = _make_environ("/__remote/posts/hello", {"args": [123]})  # int instead of str
    (status, headers), body = _call(env)
    assert status.startswith("422")
    payload = json.loads(body)
    assert payload["ok"] is False


def test_domain_error_returns_correct_status(remote_project):
    env = _make_environ("/__remote/posts/boom", {"args": []})
    (status, headers), body = _call(env)
    assert status.startswith("404")
    payload = json.loads(body)
    assert payload["error"] == "not_found"
