"""Tests for build_broadcast_provider — mirrors the jobs registry tests."""
import pytest

from fymo.broadcast.providers.base import BaseBroadcastProvider
from fymo.broadcast.providers.postgres import PostgresBroadcastProvider
from fymo.broadcast.providers.registry import (
    BroadcastProviderConfigError,
    build_broadcast_provider,
)


def test_defaults_to_postgres_when_unset():
    assert isinstance(build_broadcast_provider(None), PostgresBroadcastProvider)


def test_builds_postgres_from_bare_string():
    assert isinstance(build_broadcast_provider("postgres"), PostgresBroadcastProvider)


def test_unknown_builtin_string_raises():
    with pytest.raises(BroadcastProviderConfigError, match="unknown built-in broadcast provider: 'nope'"):
        build_broadcast_provider("nope")


def test_builds_from_type_key_with_options():
    provider = build_broadcast_provider({"type": "postgres", "database_url_env": "OTHER_DB"})
    assert isinstance(provider, PostgresBroadcastProvider)
    assert provider._database_url_env == "OTHER_DB"


def test_builds_from_dotted_class_path():
    provider = build_broadcast_provider({"class": "fymo.broadcast.providers.base.BaseBroadcastProvider"})
    assert isinstance(provider, BaseBroadcastProvider)


def test_bad_dotted_class_path_raises():
    with pytest.raises(BroadcastProviderConfigError, match="could not be imported"):
        build_broadcast_provider({"class": "totally.fake.module.Class"})


def test_missing_type_or_class_key_raises():
    with pytest.raises(BroadcastProviderConfigError, match="needs a 'type' or 'class' key"):
        build_broadcast_provider({"foo": "bar"})


def test_invalid_config_type_raises():
    with pytest.raises(BroadcastProviderConfigError, match="must be a string or object"):
        build_broadcast_provider(123)
