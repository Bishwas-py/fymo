"""Build a single StorageProvider from fymo.yml's `storage:` config.

Same escape hatch as auth/jobs/broadcasts: a bare string for a built-in, or
an object with a selector plus any extra constructor kwargs. One deliberate
difference from `fymo.core.providers.instantiate_provider`'s other callers:
there is no default. `instantiate_provider`'s `default` callback exists to
provide a sensible fallback (e.g. jobs defaults to `threaded`); storage's
`default` instead raises, since silently writing to local disk is exactly
the footgun that works in dev and quietly loses data behind a load balancer
in production.

The object form's selector key is `provider` (`{provider: local, ...}`),
not `type` like the other subsystems, to match the `storage:` section's own
shape in fymo.yml. `instantiate_provider` only recognizes `type`/`class`, so
`provider` is normalized to `type` here before delegating, rather than
reimplementing the string-or-object parsing by hand.

`project_root` is runtime context, not a fymo.yml value, so it can't live in
`opts` the way `instantiate_provider` threads config keys through to a
builtin's constructor. It's injected via a small factory closure instead
(see `_local` below) so the shared instantiate/load-class machinery still
does the string/object/dotted-class parsing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fymo.core.providers import ProviderConfigError, instantiate_provider
from fymo.storage.base import StorageProvider
from fymo.storage.providers.local import LocalStorageProvider


class StorageConfigError(ProviderConfigError):
    """Raised when `storage:` can't be turned into a provider instance, or
    is missing entirely."""


def build_storage_provider(config: Any, project_root: Path) -> StorageProvider:
    """Instantiate the configured storage provider. Raises StorageConfigError
    when `config` is falsy, on purpose, there is no built-in fallback."""

    def _default():
        raise StorageConfigError(
            "storage: is configured but empty and there is no default provider, "
            "set storage.provider (e.g. `storage: {provider: local}`)"
        )

    def _local(**opts):
        return LocalStorageProvider(project_root=project_root, **opts)

    builtins = {"local": _local}

    normalized = config
    if isinstance(config, dict):
        normalized = dict(config)
        # `expose` is route config consumed by fymo.core.expose (via
        # fymo/core/server.py), not a provider constructor kwarg.
        normalized.pop("expose", None)
        if "provider" in normalized and "type" not in normalized:
            normalized["type"] = normalized.pop("provider")

    return instantiate_provider(
        normalized,
        builtins,
        _default,
        StorageConfigError,
        what="storage provider",
        config_key="storage",
    )
