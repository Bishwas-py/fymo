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


# required: auto


class AlwaysUnconfiguredProvider(BaseProvider):
    """is_configured() always False; __init__ asserts if ever reached, so a
    test that constructs this by mistake fails loudly instead of quietly
    passing."""
    id = "always-unconfigured"
    constructed = False

    @classmethod
    def is_configured(cls) -> bool:
        return False

    def __init__(self) -> None:
        type(self).constructed = True


class TogglableProvider(BaseProvider):
    """is_configured() reflects a class attribute the test flips, standing in
    for a provider that checks os.environ at is_configured() time."""
    id = "togglable"
    configured = True

    @classmethod
    def is_configured(cls) -> bool:
        return cls.configured


class ConfigurableProvider(BaseProvider):
    """Takes a constructor kwarg so tests can confirm `required` never leaks
    into opts alongside real ones."""
    id = "configurable"
    configured = True

    def __init__(self, greeting: str = "hi") -> None:
        self.greeting = greeting

    @classmethod
    def is_configured(cls) -> bool:
        return cls.configured


class OverridesIsConfiguredButNotOptedIn(BaseProvider):
    """Overrides is_configured() to return False, but the fymo.yml entry
    never sets `required: auto`; the flag, not the hook's existence, must
    gate the behavior, so this should always construct."""
    id = "not-opted-in"

    @classmethod
    def is_configured(cls) -> bool:
        return False


def test_required_auto_provider_skipped_when_not_configured():
    AlwaysUnconfiguredProvider.constructed = False
    providers = build_providers([
        {"class": "tests.auth.test_providers.AlwaysUnconfiguredProvider", "required": "auto"},
    ])
    assert providers == []
    assert AlwaysUnconfiguredProvider.constructed is False


def test_required_auto_provider_included_when_configured():
    TogglableProvider.configured = True
    try:
        providers = build_providers([
            {"class": "tests.auth.test_providers.TogglableProvider", "required": "auto"},
        ])
        assert len(providers) == 1
        assert isinstance(providers[0], TogglableProvider)
    finally:
        TogglableProvider.configured = True


def test_required_auto_reflects_configuration_state_both_ways():
    """Same provider, same entry: flip is_configured()'s answer and the
    result flips with it."""
    TogglableProvider.configured = False
    try:
        assert build_providers([
            {"class": "tests.auth.test_providers.TogglableProvider", "required": "auto"},
        ]) == []
    finally:
        TogglableProvider.configured = True
    providers = build_providers([
        {"class": "tests.auth.test_providers.TogglableProvider", "required": "auto"},
    ])
    assert len(providers) == 1


def test_required_auto_is_popped_before_construction():
    ConfigurableProvider.configured = True
    providers = build_providers([
        {
            "class": "tests.auth.test_providers.ConfigurableProvider",
            "required": "auto",
            "greeting": "hello",
        },
    ])
    assert len(providers) == 1
    assert providers[0].greeting == "hello"


def test_provider_without_required_auto_is_always_constructed_even_with_is_configured_override():
    """The flag gates the behavior, not the mere presence of the hook."""
    providers = build_providers([
        {"class": "tests.auth.test_providers.OverridesIsConfiguredButNotOptedIn"},
    ])
    assert len(providers) == 1
    assert isinstance(providers[0], OverridesIsConfiguredButNotOptedIn)


def test_base_provider_is_configured_defaults_to_true():
    assert BaseProvider.is_configured() is True


# `required` typo / bad-value handling


class FromConfigProvider(BaseProvider):
    """Only reads named keys out of opts via from_config, like
    Clerk/Google/OIDC do; an unrecognized extra key is silently ignored
    unless the registry validates it first."""
    id = "from-config"

    def __init__(self, secret: str = "") -> None:
        self.secret = secret

    @classmethod
    def from_config(cls, opts: dict) -> "FromConfigProvider":
        return cls(secret=opts.get("secret", ""))


class FromConfigTogglableProvider(BaseProvider):
    id = "from-config-togglable"
    configured = True

    def __init__(self, secret: str = "") -> None:
        self.secret = secret

    @classmethod
    def from_config(cls, opts: dict) -> "FromConfigTogglableProvider":
        return cls(secret=opts.get("secret", ""))

    @classmethod
    def is_configured(cls) -> bool:
        return cls.configured


def test_unrecognized_required_value_raises_for_from_config_providers():
    """Previously silently dropped: from_config only reads named keys, so a
    typo'd `required` just vanished into the ignored rest of opts."""
    with pytest.raises(ProviderConfigError, match="required"):
        build_providers([
            {"class": "tests.auth.test_providers.FromConfigProvider", "required": "Auto", "secret": "x"},
        ])


def test_unrecognized_required_value_raises_for_plain_kwarg_providers():
    """Previously a raw TypeError from the constructor rejecting an
    unexpected `required` kwarg; must be the same clear ProviderConfigError
    as the from_config path."""
    with pytest.raises(ProviderConfigError, match="required"):
        build_providers([
            {"class": "tests.auth.test_providers.ConfigurableProvider", "required": "yes"},
        ])


def test_unrecognized_required_value_names_the_bad_value():
    with pytest.raises(ProviderConfigError) as exc_info:
        build_providers([
            {"class": "tests.auth.test_providers.ConfigurableProvider", "required": "Auto"},
        ])
    assert "Auto" in str(exc_info.value)


def test_required_auto_correctly_cased_still_works_for_from_config_providers():
    FromConfigTogglableProvider.configured = False
    try:
        providers = build_providers([
            {
                "class": "tests.auth.test_providers.FromConfigTogglableProvider",
                "required": "auto",
                "secret": "x",
            },
        ])
        assert providers == []
    finally:
        FromConfigTogglableProvider.configured = True
