"""Generic provider instantiation shared by auth, jobs, and broadcasts.

Each subsystem accepts the same fymo.yml escape hatch -- a bare string
for a built-in, or an object with a `type` (built-in) or `class` (dotted
path) key plus extra constructor kwargs -- and each had its own verbatim
copy of the loader. One implementation now serves all three; subsystems
keep their own error classes (subclassing ProviderConfigError) so
existing except clauses and error-message tests keep working.
"""
from __future__ import annotations

import importlib
from typing import Any, Callable, Dict, Optional, Type


class ProviderConfigError(Exception):
    """A provider config value can't be turned into a provider instance."""


def load_class(dotted: str, error_cls: Type[Exception] = ProviderConfigError):
    module_path, _, cls_name = dotted.rpartition(".")
    if not module_path or not cls_name:
        raise error_cls(f"invalid provider class path: {dotted!r}")
    try:
        mod = importlib.import_module(module_path)
        return getattr(mod, cls_name)
    except (ImportError, AttributeError) as e:
        raise error_cls(f"provider class {dotted!r} could not be imported: {e}") from e


def instantiate_provider(
    config: Any,
    builtins: Dict[str, type],
    default: Callable[[], Any],
    error_cls: Type[Exception],
    what: str,
    config_key: Optional[str] = None,
) -> Any:
    """The shared string-or-object instantiation shape. `what` names the
    config key in error messages (e.g. "job provider"); `config_key`, when
    given, overrides just the final "must be a string or object" message
    (e.g. "jobs.provider") so each subsystem's exact historical wording is
    preserved even where it doesn't match `what`."""
    if not config:
        return default()

    if isinstance(config, str):
        if config not in builtins:
            raise error_cls(f"unknown built-in {what}: {config!r}")
        return builtins[config]()

    if isinstance(config, dict):
        if "class" in config:
            cls = load_class(config["class"], error_cls)
        elif "type" in config:
            type_ = config["type"]
            if type_ not in builtins:
                raise error_cls(f"unknown built-in {what} type: {type_!r}")
            cls = builtins[type_]
        else:
            raise error_cls("provider config needs a 'type' or 'class' key")
        opts = {k: v for k, v in config.items() if k not in ("type", "class")}
        return cls(**opts) if opts else cls()

    if config_key:
        raise error_cls(f"{config_key} must be a string or object, got {type(config).__name__}")
    raise error_cls(f"{what} config must be a string or object, got {type(config).__name__}")
