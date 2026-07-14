"""Build auth providers from `fymo.yml` config and wire their seams.

Config accepts a bare string for built-ins (`password`) or an object with a
`type` (built-in) or `class` (dotted path to a custom provider) — the same
escape hatch as `UserStore`. Secrets are read from env by the providers
themselves, never from the config.
"""
from __future__ import annotations

from typing import Any, List, Optional

from fymo.auth.context import register_session_resolver, reset_session_resolvers
from fymo.auth.providers.base import AuthProvider, BaseProvider
from fymo.auth.providers.clerk import ClerkProvider
from fymo.auth.providers.oauth import GoogleProvider, OIDCProvider
from fymo.auth.providers.password import PasswordProvider
from fymo.core.providers import ProviderConfigError as _CoreProviderConfigError
from fymo.core.providers import load_class

# Built-in provider types. New providers register here as they land.
_BUILTINS = {
    "password": PasswordProvider,
    "google": GoogleProvider,
    "oidc": OIDCProvider,
    "clerk": ClerkProvider,
}


class ProviderConfigError(_CoreProviderConfigError):
    """Raised when `auth.providers` can't be turned into provider instances."""


def _instantiate(entry: Any) -> Optional[AuthProvider]:
    """Returns None when a `required: auto` entry's provider declines
    (is_configured() -> False); the caller filters those out rather than
    including an inert placeholder in the provider list."""
    if isinstance(entry, str):
        if entry not in _BUILTINS:
            raise ProviderConfigError(f"unknown built-in provider: {entry!r}")
        return _BUILTINS[entry]()

    if isinstance(entry, dict):
        if "class" in entry:
            cls = load_class(entry["class"], ProviderConfigError)
        elif "type" in entry:
            type_ = entry["type"]
            if type_ not in _BUILTINS:
                raise ProviderConfigError(f"unknown built-in provider type: {type_!r}")
            cls = _BUILTINS[type_]
        else:
            raise ProviderConfigError("provider config needs a 'type' or 'class' key")
        opts = {k: v for k, v in entry.items() if k not in ("type", "class")}
        # `required` is an explicit opt-in (only "auto" is recognized, never
        # automatic); pop it before it can reach the constructor as a stray
        # kwarg, and validate it explicitly here rather than letting a typo
        # silently vanish into an ignored from_config() key on one provider
        # while raising a raw TypeError from cls(**opts) on another.
        if "required" in opts:
            required_value = opts.pop("required")
            if required_value != "auto":
                raise ProviderConfigError(
                    f"unknown value for provider 'required': {required_value!r} "
                    f'(only "auto" is supported); entry: {entry!r}'
                )
            if not cls.is_configured():
                return None
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
    instantiated = (_instantiate(entry) for entry in config)
    return [provider for provider in instantiated if provider is not None]


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
