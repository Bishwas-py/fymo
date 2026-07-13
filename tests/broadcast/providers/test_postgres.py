"""Tests for PostgresBroadcastProvider against a real Postgres — LISTEN/
NOTIFY round-trips, cross-connection (publisher and listener on separate
connections, as web/worker processes are in production).

Skipped without TEST_DATABASE_URL, like the Procrastinate provider tests.
"""
import json
import os
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="needs TEST_DATABASE_URL pointing at a real Postgres instance",
)


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    from fymo.broadcast.providers.postgres import PostgresBroadcastProvider
    return PostgresBroadcastProvider()


def _collect_events(provider, key, out, ready, count=1):
    gen = provider.listen(key, ready=ready)
    for event in gen:
        if event is None:  # idle tick — keepalive signal, not an event
            continue
        out.append(event)
        if len(out) >= count:
            break


def test_publish_reaches_a_listener_on_another_connection(provider):
    key = "fymo_bc_test_roundtrip"
    events: list = []
    ready = threading.Event()
    t = threading.Thread(target=_collect_events, args=(provider, key, events, ready), daemon=True)
    t.start()
    assert ready.wait(timeout=5), "listener never issued LISTEN"

    provider.publish(key, json.dumps({"status": "passed"}))
    t.join(timeout=5)

    assert events == [json.dumps({"status": "passed"})]


def test_listener_only_sees_its_own_channel(provider):
    key_a, key_b = "fymo_bc_test_chan_a", "fymo_bc_test_chan_b"
    events: list = []
    ready = threading.Event()
    t = threading.Thread(target=_collect_events, args=(provider, key_a, events, ready), daemon=True)
    t.start()
    assert ready.wait(timeout=5)

    provider.publish(key_b, '"not for a"')
    provider.publish(key_a, '"for a"')
    t.join(timeout=5)

    assert events == ['"for a"']


def test_listen_yields_none_idle_ticks_during_silence(provider):
    """The idle tick is the SSE keepalive/disconnect-detection mechanism —
    it must arrive even when nothing is published."""
    gen = provider.listen("fymo_bc_test_idle", idle_timeout=0.2)
    tick = next(gen)
    gen.close()
    assert tick is None


def test_publish_rejects_payloads_over_the_notify_limit(provider):
    with pytest.raises(ValueError, match="8000"):
        provider.publish("fymo_bc_test_big", "x" * 8001)


def test_id_is_postgres(provider):
    assert provider.id == "postgres"


def test_missing_database_url_raises_a_clear_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from fymo.broadcast.providers.postgres import PostgresBroadcastProvider
    p = PostgresBroadcastProvider()
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        p.publish("fymo_bc_x", "{}")
