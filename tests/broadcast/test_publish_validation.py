"""Dev-mode payload validation in publish(): a channel's return-type
TypedDict is the contract for `data`; a mismatch is a warning, never a
block. publish() must still deliver and never raise on a bad payload."""
from pathlib import Path

import pytest

from fymo.broadcast import init_broadcasts, publish, reset_broadcasts, set_broadcast_provider
import fymo.broadcast as broadcast_mod
from fymo.broadcast.providers.base import BaseBroadcastProvider


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
    broadcast_mod._dev_mode = False


@pytest.fixture
def typed_channel(tmp_path: Path):
    """A channel whose return annotation is a TypedDict with one required
    and one optional key, enough to exercise missing/extra key checks."""
    bdir = tmp_path / "app" / "broadcasts"
    bdir.mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").touch()
    (bdir / "__init__.py").touch()
    (bdir / "runs.py").write_text(
        "from typing import TypedDict, NotRequired\n"
        "\n"
        "class RunStatus(TypedDict):\n"
        "    status: str\n"
        "    error: NotRequired[str]\n"
        "\n"
        "def run_status(run_id: str) -> RunStatus:\n"
        "    ...\n"
    )
    return tmp_path


@pytest.fixture
def untyped_channel(tmp_path: Path):
    """A channel with no TypedDict return annotation, matching today's
    default `-> dict:` / `...` body style. Must never be validated."""
    bdir = tmp_path / "app" / "broadcasts"
    bdir.mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").touch()
    (bdir / "__init__.py").touch()
    (bdir / "runs.py").write_text("def run_status(run_id: str) -> dict:\n    ...\n")
    return tmp_path


def _publish_matching(run_id="r1"):
    publish("run_status", run_id=run_id, data={"status": "passed"})


def _publish_missing_required(run_id="r1"):
    publish("run_status", run_id=run_id, data={"error": "boom"})


def _publish_extra_key(run_id="r1"):
    publish("run_status", run_id=run_id, data={"status": "passed", "bogus": 1})


def test_dev_mode_matching_payload_produces_no_warning(typed_channel, caplog):
    broadcast_mod._dev_mode = True
    init_broadcasts(typed_channel, None)
    set_broadcast_provider(CapturingProvider())
    with caplog.at_level("WARNING", logger="fymo.broadcast"):
        _publish_matching()
    assert caplog.records == []


def test_dev_mode_missing_required_key_warns_with_channel_and_key(typed_channel, caplog):
    broadcast_mod._dev_mode = True
    init_broadcasts(typed_channel, None)
    set_broadcast_provider(CapturingProvider())
    with caplog.at_level("WARNING", logger="fymo.broadcast"):
        _publish_missing_required()
    assert len(caplog.records) == 1
    message = caplog.records[0].message
    assert "run_status" in message
    assert "status" in message


def test_dev_mode_extra_key_warns_with_channel_and_key(typed_channel, caplog):
    broadcast_mod._dev_mode = True
    init_broadcasts(typed_channel, None)
    set_broadcast_provider(CapturingProvider())
    with caplog.at_level("WARNING", logger="fymo.broadcast"):
        _publish_extra_key()
    assert len(caplog.records) == 1
    message = caplog.records[0].message
    assert "run_status" in message
    assert "bogus" in message


def test_prod_mode_mismatched_payload_produces_no_warning_and_does_not_raise(typed_channel, caplog):
    broadcast_mod._dev_mode = False
    init_broadcasts(typed_channel, None)
    p = CapturingProvider()
    set_broadcast_provider(p)
    with caplog.at_level("WARNING", logger="fymo.broadcast"):
        _publish_missing_required()
        _publish_extra_key()
    assert caplog.records == []
    assert len(p.published) == 2  # still delivered, validation never blocks


def test_untyped_channel_is_never_validated_even_in_dev_mode(untyped_channel, caplog):
    broadcast_mod._dev_mode = True
    init_broadcasts(untyped_channel, None)
    set_broadcast_provider(CapturingProvider())
    with caplog.at_level("WARNING", logger="fymo.broadcast"):
        publish("run_status", run_id="r1", data={"anything": "goes", "no": "contract"})
    assert caplog.records == []
