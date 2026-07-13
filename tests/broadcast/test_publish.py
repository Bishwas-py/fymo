"""Tests for fymo.broadcast.publish() and the provider/channel singleton."""
import json
import threading
from pathlib import Path

import pytest

from fymo.broadcast import (
    channel_key,
    get_broadcast_provider,
    init_broadcasts,
    publish,
    reset_broadcasts,
    set_broadcast_provider,
)
from fymo.broadcast.providers.base import BaseBroadcastProvider
from fymo.broadcast.providers.postgres import PostgresBroadcastProvider


class CapturingProvider(BaseBroadcastProvider):
    id = "capturing"

    def __init__(self):
        self.published = []

    def publish(self, key, payload):
        self.published.append((key, payload))


@pytest.fixture(autouse=True)
def _reset():
    reset_broadcasts()
    yield
    reset_broadcasts()


@pytest.fixture
def app_with_channel(tmp_path: Path):
    bdir = tmp_path / "app" / "broadcasts"
    bdir.mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").touch()
    (bdir / "__init__.py").touch()
    (bdir / "runs.py").write_text("def run_status(run_id: str) -> dict:\n    ...\n")
    return tmp_path


def test_get_broadcast_provider_defaults_to_postgres():
    assert isinstance(get_broadcast_provider(), PostgresBroadcastProvider)


def test_set_broadcast_provider_overrides():
    p = CapturingProvider()
    set_broadcast_provider(p)
    assert get_broadcast_provider() is p


def test_publish_routes_through_the_provider_with_the_channel_key(app_with_channel):
    init_broadcasts(app_with_channel, None)
    p = CapturingProvider()
    set_broadcast_provider(p)

    publish("run_status", run_id="r1", data={"status": "passed"})

    key, payload = p.published[0]
    assert key == channel_key("runs", "run_status", {"run_id": "r1"})
    assert json.loads(payload) == {"status": "passed"}


def test_publish_unknown_channel_raises(app_with_channel):
    init_broadcasts(app_with_channel, None)
    set_broadcast_provider(CapturingProvider())
    with pytest.raises(ValueError, match="unknown broadcast channel: 'nope'"):
        publish("nope", data={})


def test_publish_with_wrong_args_raises(app_with_channel):
    init_broadcasts(app_with_channel, None)
    set_broadcast_provider(CapturingProvider())
    with pytest.raises(TypeError):
        publish("run_status", flow_id="wrong-name", data={})


def test_publish_before_init_raises_a_clear_error():
    with pytest.raises(RuntimeError, match="init_broadcasts"):
        publish("anything", data={})
