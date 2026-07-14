"""Blog example: the post_activity broadcast channel is the reference
example for a real guard body: deny via NotFound when the post doesn't
exist, allow (open channel) otherwise. Exercised at the WSGI level, same
approach as tests/broadcast/test_sse.py, but against the real
app/broadcasts/posts.py shipped in examples/blog_app rather than a
synthetic stub."""
import sys
from pathlib import Path

import pytest

from fymo.broadcast import init_broadcasts, reset_broadcasts, set_broadcast_provider
from fymo.broadcast.providers.base import BaseBroadcastProvider
from fymo.broadcast.sse import handle_broadcast
from fymo.remote import identity


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


def test_channel_is_discovered_from_the_real_example(blog_app: Path):
    channels = init_broadcasts(blog_app, None)
    from fymo.broadcast import get_channels
    module, fn = get_channels()["post_activity"]
    assert module == "posts"
    assert fn.__name__ == "post_activity"


def test_subscribing_to_a_missing_post_is_rejected(blog_app: Path):
    init_broadcasts(blog_app, None)
    captured, body, provider = _call(_environ("/_fymo/broadcast/posts/post_activity", "slug=does-not-exist"))
    assert captured["status"].startswith("403")
    assert provider.listened_keys == []  # guard ran and rejected before any LISTEN


def test_subscribing_to_a_real_post_is_allowed(blog_app: Path):
    from tests.integration._seed_helpers import seed_test_post
    seed_test_post("welcome-to-fymo")
    init_broadcasts(blog_app, None)
    captured, body, provider = _call(_environ("/_fymo/broadcast/posts/post_activity", "slug=welcome-to-fymo"))
    assert captured["status"] == "200 OK"
    list(body)  # drain the generator so listen() actually runs
    assert len(provider.listened_keys) == 1
