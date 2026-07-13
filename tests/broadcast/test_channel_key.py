"""Tests for fymo.broadcast.channel_key — the module+channel+args →
LISTEN/NOTIFY channel-name encoding. Must be deterministic, collision-safe
across arg *values*, and a valid Postgres identifier under 63 chars."""
import re

from fymo.broadcast import channel_key


def test_is_deterministic():
    a = channel_key("runs", "run_status", {"run_id": "abc"})
    b = channel_key("runs", "run_status", {"run_id": "abc"})
    assert a == b


def test_different_args_get_different_keys():
    a = channel_key("runs", "run_status", {"run_id": "abc"})
    b = channel_key("runs", "run_status", {"run_id": "xyz"})
    assert a != b


def test_different_channels_get_different_keys():
    a = channel_key("runs", "run_status", {"run_id": "abc"})
    b = channel_key("runs", "run_started", {"run_id": "abc"})
    assert a != b


def test_different_modules_get_different_keys():
    a = channel_key("runs", "status", {"id": "abc"})
    b = channel_key("flows", "status", {"id": "abc"})
    assert a != b


def test_arg_order_does_not_matter():
    a = channel_key("m", "c", {"x": "1", "y": "2"})
    b = channel_key("m", "c", {"y": "2", "x": "1"})
    assert a == b


def test_is_a_valid_postgres_identifier_under_63_chars():
    key = channel_key("some_long_module_name", "some_long_channel_name", {"run_id": "x" * 500})
    assert re.fullmatch(r"[a-z_][a-z0-9_]*", key)
    assert len(key) <= 63
    assert key.startswith("fymo_bc_")


def test_no_args_is_valid():
    assert channel_key("m", "c", {}) == channel_key("m", "c", {})
