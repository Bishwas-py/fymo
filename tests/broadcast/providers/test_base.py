"""Tests for the BroadcastProvider seam (mirrors JobProvider's base contract)."""
import pytest

from fymo.broadcast.providers.base import BaseBroadcastProvider, BroadcastProvider


def test_base_provider_publish_raises_not_implemented():
    provider = BaseBroadcastProvider()
    with pytest.raises(NotImplementedError):
        provider.publish("fymo_bc_abc", "{}")


def test_base_provider_listen_raises_not_implemented():
    provider = BaseBroadcastProvider()
    with pytest.raises(NotImplementedError):
        next(provider.listen("fymo_bc_abc"))


def test_base_provider_satisfies_the_protocol():
    assert isinstance(BaseBroadcastProvider(), BroadcastProvider)
