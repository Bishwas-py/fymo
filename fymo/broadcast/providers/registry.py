"""Build a single BroadcastProvider from fymo.yml's `broadcasts:` config.

Same escape hatch as auth and jobs: a bare string for a built-in, or an
object with a `type` (built-in) or `class` (dotted path to a custom
provider) key plus any extra constructor kwargs.
"""
from __future__ import annotations

from typing import Any

from fymo.broadcast.providers.base import BroadcastProvider
from fymo.broadcast.providers.postgres import PostgresBroadcastProvider
from fymo.core.providers import ProviderConfigError, instantiate_provider

_BUILTINS = {
    "postgres": PostgresBroadcastProvider,
}


class BroadcastProviderConfigError(ProviderConfigError):
    """Raised when `broadcasts.provider` can't be turned into a provider."""


def build_broadcast_provider(config: Any) -> BroadcastProvider:
    """Instantiate the configured broadcast provider; `postgres` when
    `broadcasts.provider` is unset."""
    return instantiate_provider(
        config,
        _BUILTINS,
        PostgresBroadcastProvider,
        BroadcastProviderConfigError,
        what="broadcast provider",
        config_key="broadcasts.provider",
    )
