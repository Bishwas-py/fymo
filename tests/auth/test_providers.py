"""AuthProvider registry: build from config + wire the resolver chain."""
import pytest

from fymo.auth import context as auth_context
from fymo.auth.providers.base import AuthProvider, BaseProvider
from fymo.auth.providers.password import PasswordProvider
from fymo.auth.providers.registry import (
    ProviderConfigError,
    build_providers,
    install_providers,
)


def test_password_provider_exposes_the_expected_remote_functions():
    fns = PasswordProvider().remote_functions()
    assert set(fns) == {
        "signup", "login", "logout", "me",
        "request_email_verification", "verify_email",
        "request_password_reset", "reset_password",
    }
    assert all(callable(f) for f in fns.values())


def test_password_provider_satisfies_the_protocol():
    assert isinstance(PasswordProvider(), AuthProvider)


def test_build_defaults_to_password_when_unset():
    providers = build_providers(None)
    assert [p.id for p in providers] == ["password"]


def test_build_from_string_and_object_forms():
    providers = build_providers(["password", {"type": "password"}])
    assert [p.id for p in providers] == ["password", "password"]


def test_unknown_builtin_raises():
    with pytest.raises(ProviderConfigError):
        build_providers(["nope"])
    with pytest.raises(ProviderConfigError):
        build_providers([{"type": "nope"}])


def test_object_needs_type_or_class():
    with pytest.raises(ProviderConfigError):
        build_providers([{"redirect_path": "/x"}])


def test_custom_provider_via_dotted_class_path():
    providers = build_providers(
        [{"class": "tests.auth.test_providers.DummyTokenProvider"}]
    )
    assert isinstance(providers[0], DummyTokenProvider)


def test_install_registers_only_overriding_resolvers():
    """A credential provider (no resolve_session) adds nothing to the chain; a
    token provider that overrides it does."""
    auth_context.reset_session_resolvers()
    install_providers([PasswordProvider(), DummyTokenProvider()])
    # Only DummyTokenProvider overrides resolve_session.
    assert len(auth_context._session_resolvers) == 1
    auth_context.reset_session_resolvers()


class DummyTokenProvider(BaseProvider):
    id = "dummy"

    def resolve_session(self, event):
        return None
