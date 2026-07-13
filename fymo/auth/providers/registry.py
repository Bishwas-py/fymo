"""Build auth providers from `fymo.yml` config and wire their seams.

Config accepts a bare string for built-ins (`password`) or an object with a
`type` (built-in) or `class` (dotted path to a custom provider) — the same
escape hatch as `UserStore`. Secrets are read from env by the providers
themselves, never from the config.
"""
from __future__ import annotations

import importlib
from typing import Any, List

from fymo.auth.context import register_session_resolver, reset_session_resolvers
from fymo.auth.providers.base import AuthProvider, BaseProvider
from fymo.auth.providers.clerk import ClerkProvider
from fymo.auth.providers.oauth import GoogleProvider, OIDCProvider
from fymo.auth.providers.password import PasswordProvider

# Built-in provider types. New providers register here as they land.
_BUILTINS = {
    "password": PasswordProvider,
    "google": GoogleProvider,
    "oidc": OIDCProvider,
    "clerk": ClerkProvider,
}


class ProviderConfigError(Exception):
    """Raised when `auth.providers` can't be turned into provider instances."""


def _load_class(dotted: str):
    module_path, _, cls_name = dotted.rpartition(".")
    if not module_path or not cls_name:
        raise ProviderConfigError(f"invalid provider class path: {dotted!r}")
    try:
        mod = importlib.import_module(module_path)
        return getattr(mod, cls_name)
    except (ImportError, AttributeError) as e:
        raise ProviderConfigError(f"provider class {dotted!r} could not be imported: {e}") from e


def _instantiate(entry: Any) -> AuthProvider:
    if isinstance(entry, str):
        if entry not in _BUILTINS:
            raise ProviderConfigError(f"unknown built-in provider: {entry!r}")
        return _BUILTINS[entry]()

    if isinstance(entry, dict):
        if "class" in entry:
            cls = _load_class(entry["class"])
        elif "type" in entry:
            type_ = entry["type"]
            if type_ not in _BUILTINS:
                raise ProviderConfigError(f"unknown built-in provider type: {type_!r}")
            cls = _BUILTINS[type_]
        else:
            raise ProviderConfigError("provider config needs a 'type' or 'class' key")
        opts = {k: v for k, v in entry.items() if k not in ("type", "class")}
        # Providers with env-backed secrets expose from_config(opts); others
        # take plain kwargs.
        if hasattr(cls, "from_config"):
            return cls.from_config(opts)
        return cls(**opts) if opts else cls()

    raise ProviderConfigError(f"provider config must be a string or object, got {type(entry).__name__}")


def build_providers(config: List[Any] | None) -> List[AuthProvider]:
    """Instantiate providers from `auth.providers`. Defaults to `[password]`."""
    if not config:
        return [PasswordProvider()]
    return [_instantiate(entry) for entry in config]


def system_remote_modules(providers: List[AuthProvider]) -> dict:
    """Collect providers' remote functions as {module_name: {fn_name: callable}}.

    The single source of truth for framework-shipped remote functions (e.g.
    password's signup/login/logout/me under `auth`). Both the build (codegen)
    and the runtime router read this — no hardcoded module list anywhere.
    """
    modules: dict = {}
    for provider in providers:
        fns = provider.remote_functions()
        if not fns:
            continue
        name = getattr(provider, "remote_module", "") or provider.id
        modules[name] = fns
    return modules


def install_providers(providers: List[AuthProvider]) -> None:
    """Register each provider's session resolver into current_user()'s chain.

    Only providers that actually override resolve_session contribute one, so
    inert credential/OAuth providers don't add no-op links to the chain.
    """
    reset_session_resolvers()
    for provider in providers:
        if type(provider).resolve_session is not BaseProvider.resolve_session:
            register_session_resolver(provider.resolve_session)
