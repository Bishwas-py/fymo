"""Broadcast guard bodies end to end: deny via NotFound when the row
does not exist, allow (open channel) otherwise. Exercised at the WSGI
level, same approach as tests/broadcast/test_sse.py, but through the
real app/broadcasts discovery against a real app copy. The regenerated
blog example ships no broadcasts of its own, so the channel is
test-owned, written onto the copy and guarding against the generated
posts remote's rows.
"""
import sys
from pathlib import Path

import pytest

from fymo.broadcast import init_broadcasts, reset_broadcasts, set_broadcast_provider
from fymo.broadcast.providers.base import BaseBroadcastProvider
from fymo.broadcast.sse import handle_broadcast
from fymo.remote import identity

_CHANNEL = '''"""Test-owned channel over the generated posts rows."""
from typing import TypedDict

from app.remote.posts import list_posts
from fymo.remote import NotFound


class PostActivity(TypedDict):
    kind: str


def post_activity(id: str) -> PostActivity:
    # Deny subscribing to a post that is not there, rather than silently
    # opening a channel nothing will ever publish to.
    if not any(str(row["id"]) == id for row in list_posts()):
        raise NotFound(f"post {id} not found")
'''


class FakeProvider(BaseBroadcastProvider):
    id = "fake"

    def __init__(self, events=()):
        self._events = list(events)
        self.listened_keys = []

    def listen(self, key, ready=None, **kwargs):
        self.listened_keys.append(key)
        if ready is not None:
            ready.set()
        yield from self._events


@pytest.fixture(autouse=True)
def _reset():
    identity.set_secret(b"test-secret-32-bytes-loooooooong")
    reset_broadcasts()
    yield
    reset_broadcasts()


@pytest.fixture
def broadcast_blog(blog_app: Path) -> Path:
    bdir = blog_app / "app" / "broadcasts"
    bdir.mkdir()
    (bdir / "__init__.py").write_text("")
    (bdir / "activity.py").write_text(_CHANNEL)
    return blog_app


def _environ(path: str, query: str = "") -> dict:
    return {"PATH_INFO": path, "QUERY_STRING": query, "REQUEST_METHOD": "GET"}


def _call(environ):
    provider = FakeProvider()
    set_broadcast_provider(provider)
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = handle_broadcast(environ, start_response)
    return captured, body, provider


def test_channel_is_discovered_from_the_app(broadcast_blog: Path):
    init_broadcasts(broadcast_blog, None)
    from fymo.broadcast import get_channels
    module, fn = get_channels()["post_activity"]
    assert module == "activity"
    assert fn.__name__ == "post_activity"


def test_subscribing_to_a_missing_post_is_rejected(broadcast_blog: Path):
    init_broadcasts(broadcast_blog, None)
    captured, body, provider = _call(_environ("/_fymo/broadcast/activity/post_activity", "id=999"))
    assert captured["status"].startswith("403")
    assert provider.listened_keys == []  # guard ran and rejected before any LISTEN


def test_subscribing_to_a_real_post_is_allowed(broadcast_blog: Path):
    # The generated posts remote seeds row id 1.
    init_broadcasts(broadcast_blog, None)
    captured, body, provider = _call(_environ("/_fymo/broadcast/activity/post_activity", "id=1"))
    assert captured["status"] == "200 OK"
    list(body)  # drain the generator so listen() actually runs
    assert len(provider.listened_keys) == 1
