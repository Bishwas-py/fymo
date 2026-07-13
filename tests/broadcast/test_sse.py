"""Tests for the /_fymo/broadcast/<module>/<channel> SSE endpoint handler.

Uses a fake provider (no Postgres needed): the handler's job is channel
resolution, the guard, and SSE framing — transport is the provider's
problem and is tested separately.
"""
import threading
from pathlib import Path

import pytest

from fymo.broadcast import init_broadcasts, reset_broadcasts, set_broadcast_provider
from fymo.broadcast.providers.base import BaseBroadcastProvider
from fymo.broadcast.sse import handle_broadcast


class FakeProvider(BaseBroadcastProvider):
    id = "fake"

    def __init__(self, events):
        self._events = events
        self.listened_keys = []

    def listen(self, key, ready=None, **kwargs):
        self.listened_keys.append(key)
        if ready is not None:
            ready.set()
        yield from self._events


@pytest.fixture(autouse=True)
def _reset():
    # The guard runs inside the same request scope remote functions get,
    # which needs the identity secret FymoApp installs at startup.
    from fymo.remote import identity
    identity.set_secret(b"test-secret-32-bytes-loooooooong")
    reset_broadcasts()
    yield
    reset_broadcasts()


@pytest.fixture
def app_root(tmp_path: Path) -> Path:
    bdir = tmp_path / "app" / "broadcasts"
    bdir.mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").touch()
    (bdir / "__init__.py").touch()
    (bdir / "runs.py").write_text(
        "def run_status(run_id: str) -> dict:\n"
        "    ...\n"
        "\n"
        "def guarded(run_id: str) -> dict:\n"
        "    raise PermissionError('not yours')\n"
        "\n"
        "def refused(run_id: str) -> dict:\n"
        "    return False\n"
    )
    return tmp_path


def _environ(path: str, query: str = "") -> dict:
    return {"PATH_INFO": path, "QUERY_STRING": query, "REQUEST_METHOD": "GET"}


def _call(environ, events=('{"status": "passed"}',)):
    provider = FakeProvider(list(events))
    set_broadcast_provider(provider)
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = handle_broadcast(environ, start_response)
    return captured, body, provider


def test_streams_events_as_sse_frames(app_root):
    init_broadcasts(app_root, None)
    captured, body, provider = _call(
        _environ("/_fymo/broadcast/runs/run_status", "run_id=r1"),
        events=['{"status": "passed"}', None, '{"status": "failed"}'],
    )
    frames = list(body)
    assert captured["status"] == "200 OK"
    assert captured["headers"]["Content-Type"] == "text/event-stream"
    assert frames[0] == b": subscribed\n\n"  # immediate first byte: fires
    # EventSource `open` and flushes proxy buffers before the first event
    assert frames[1] == b'data: {"status": "passed"}\n\n'
    assert frames[2] == b": keepalive\n\n"  # None idle tick -> SSE comment
    assert frames[3] == b'data: {"status": "failed"}\n\n'


def test_listens_on_the_channel_key_for_the_given_args(app_root):
    from fymo.broadcast import channel_key
    init_broadcasts(app_root, None)
    _, body, provider = _call(_environ("/_fymo/broadcast/runs/run_status", "run_id=r1"))
    list(body)
    assert provider.listened_keys == [channel_key("runs", "run_status", {"run_id": "r1"})]


def test_unknown_channel_404s(app_root):
    init_broadcasts(app_root, None)
    captured, body, _ = _call(_environ("/_fymo/broadcast/runs/nope", "run_id=r1"))
    assert captured["status"].startswith("404")


def test_wrong_module_for_channel_404s(app_root):
    init_broadcasts(app_root, None)
    captured, body, _ = _call(_environ("/_fymo/broadcast/flows/run_status", "run_id=r1"))
    assert captured["status"].startswith("404")


def test_missing_required_arg_422s(app_root):
    init_broadcasts(app_root, None)
    captured, body, _ = _call(_environ("/_fymo/broadcast/runs/run_status", ""))
    assert captured["status"].startswith("422")


def test_guard_raise_403s(app_root):
    init_broadcasts(app_root, None)
    captured, body, provider = _call(_environ("/_fymo/broadcast/runs/guarded", "run_id=r1"))
    assert captured["status"].startswith("403")
    assert provider.listened_keys == []  # rejected before any LISTEN


def test_guard_returning_false_403s(app_root):
    init_broadcasts(app_root, None)
    captured, body, _ = _call(_environ("/_fymo/broadcast/runs/refused", "run_id=r1"))
    assert captured["status"].startswith("403")


def test_open_channel_guard_body_allows(app_root):
    """A `...` body (the common case) returns Ellipsis — which must count
    as allow, not be mistaken for truthiness rejection."""
    init_broadcasts(app_root, None)
    captured, body, _ = _call(_environ("/_fymo/broadcast/runs/run_status", "run_id=r1"))
    assert captured["status"] == "200 OK"
