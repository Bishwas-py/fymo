"""Build a single JobProvider from fymo.yml's `jobs:` config.

Mirrors fymo.auth.providers.registry's escape hatch exactly: a bare string
for a built-in, or an object with a `type` (built-in) or `class` (dotted
path to a custom provider) key plus any extra kwargs.
"""
from __future__ import annotations

import importlib
from typing import Any

from fymo.jobs.providers.base import JobProvider
from fymo.jobs.providers.procrastinate import ProcrastinateJobProvider
from fymo.jobs.providers.threaded import ThreadedJobProvider

_BUILTINS = {
    "threaded": ThreadedJobProvider,
    "procrastinate": ProcrastinateJobProvider,
}


class JobProviderConfigError(Exception):
    """Raised when `jobs.provider` can't be turned into a provider instance."""


def _load_class(dotted: str):
    module_path, _, cls_name = dotted.rpartition(".")
    if not module_path or not cls_name:
        raise JobProviderConfigError(f"invalid provider class path: {dotted!r}")
    try:
        mod = importlib.import_module(module_path)
        return getattr(mod, cls_name)
    except (ImportError, AttributeError) as e:
        raise JobProviderConfigError(f"provider class {dotted!r} could not be imported: {e}") from e


def build_job_provider(config: Any) -> JobProvider:
    """Instantiate the configured job provider. Defaults to `threaded` when
    `jobs.provider` is unset (mirrors auth's default-to-`password`)."""
    if not config:
        return ThreadedJobProvider()

    if isinstance(config, str):
        if config not in _BUILTINS:
            raise JobProviderConfigError(f"unknown built-in job provider: {config!r}")
        return _BUILTINS[config]()

    if isinstance(config, dict):
        if "class" in config:
            cls = _load_class(config["class"])
        elif "type" in config:
            type_ = config["type"]
            if type_ not in _BUILTINS:
                raise JobProviderConfigError(f"unknown built-in job provider type: {type_!r}")
            cls = _BUILTINS[type_]
        else:
            raise JobProviderConfigError("provider config needs a 'type' or 'class' key")
        opts = {k: v for k, v in config.items() if k not in ("type", "class")}
        return cls(**opts) if opts else cls()

    raise JobProviderConfigError(f"jobs.provider must be a string or object, got {type(config).__name__}")
