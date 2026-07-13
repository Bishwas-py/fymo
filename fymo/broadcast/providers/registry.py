"""Build a single BroadcastProvider from fymo.yml's `broadcasts:` config.

Same escape hatch as auth and jobs: a bare string for a built-in, or an
object with a `type` (built-in) or `class` (dotted path to a custom
provider) key plus any extra constructor kwargs.
"""
from __future__ import annotations

import importlib
from typing import Any

from fymo.broadcast.providers.base import BroadcastProvider
from fymo.broadcast.providers.postgres import PostgresBroadcastProvider

_BUILTINS = {
    "postgres": PostgresBroadcastProvider,
}


class BroadcastProviderConfigError(Exception):
    """Raised when `broadcasts.provider` can't be turned into a provider."""


def _load_class(dotted: str):
    module_path, _, cls_name = dotted.rpartition(".")
    if not module_path or not cls_name:
        raise BroadcastProviderConfigError(f"invalid provider class path: {dotted!r}")
    try:
        mod = importlib.import_module(module_path)
        return getattr(mod, cls_name)
    except (ImportError, AttributeError) as e:
        raise BroadcastProviderConfigError(f"provider class {dotted!r} could not be imported: {e}") from e


def build_broadcast_provider(config: Any) -> BroadcastProvider:
    """Instantiate the configured broadcast provider; `postgres` when
    `broadcasts.provider` is unset."""
    if not config:
        return PostgresBroadcastProvider()

    if isinstance(config, str):
        if config not in _BUILTINS:
            raise BroadcastProviderConfigError(f"unknown built-in broadcast provider: {config!r}")
        return _BUILTINS[config]()

    if isinstance(config, dict):
        if "class" in config:
            cls = _load_class(config["class"])
        elif "type" in config:
            type_ = config["type"]
            if type_ not in _BUILTINS:
                raise BroadcastProviderConfigError(f"unknown built-in broadcast provider type: {type_!r}")
            cls = _BUILTINS[type_]
        else:
            raise BroadcastProviderConfigError("provider config needs a 'type' or 'class' key")
        opts = {k: v for k, v in config.items() if k not in ("type", "class")}
        return cls(**opts) if opts else cls()

    raise BroadcastProviderConfigError(f"broadcasts.provider must be a string or object, got {type(config).__name__}")
