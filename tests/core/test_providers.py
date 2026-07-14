"""Tests for fymo.core.providers — the generic config→provider instantiator
shared by auth, jobs, and broadcasts."""
import pytest

from fymo.core.providers import ProviderConfigError, instantiate_provider, load_class


class _Widget:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _DefaultWidget:
    pass


_BUILTINS = {"widget": _Widget}


def test_falsy_config_returns_default():
    result = instantiate_provider(None, _BUILTINS, _DefaultWidget, ProviderConfigError, what="thing")
    assert isinstance(result, _DefaultWidget)


def test_builds_from_bare_string():
    result = instantiate_provider("widget", _BUILTINS, _DefaultWidget, ProviderConfigError, what="thing")
    assert isinstance(result, _Widget)


def test_unknown_builtin_string_raises():
    with pytest.raises(ProviderConfigError, match="unknown built-in thing: 'nope'"):
        instantiate_provider("nope", _BUILTINS, _DefaultWidget, ProviderConfigError, what="thing")


def test_builds_from_type_key():
    result = instantiate_provider({"type": "widget"}, _BUILTINS, _DefaultWidget, ProviderConfigError, what="thing")
    assert isinstance(result, _Widget)


def test_unknown_type_key_raises():
    with pytest.raises(ProviderConfigError, match="unknown built-in thing type: 'nope'"):
        instantiate_provider({"type": "nope"}, _BUILTINS, _DefaultWidget, ProviderConfigError, what="thing")


def test_builds_from_dotted_class_path():
    result = instantiate_provider(
        {"class": "tests.core.test_providers._Widget"},
        _BUILTINS, _DefaultWidget, ProviderConfigError, what="thing",
    )
    assert isinstance(result, _Widget)


def test_dict_missing_type_or_class_raises():
    with pytest.raises(ProviderConfigError, match="needs a 'type' or 'class' key"):
        instantiate_provider({"foo": "bar"}, _BUILTINS, _DefaultWidget, ProviderConfigError, what="thing")


def test_extra_kwargs_passed_to_constructor():
    result = instantiate_provider(
        {"type": "widget", "size": 3}, _BUILTINS, _DefaultWidget, ProviderConfigError, what="thing",
    )
    assert result.kwargs == {"size": 3}


def test_invalid_config_type_raises():
    with pytest.raises(ProviderConfigError, match="must be a string or object"):
        instantiate_provider(123, _BUILTINS, _DefaultWidget, ProviderConfigError, what="thing")


def test_config_key_overrides_final_message():
    with pytest.raises(ProviderConfigError, match=r"^thing\.provider must be a string or object"):
        instantiate_provider(
            123, _BUILTINS, _DefaultWidget, ProviderConfigError, what="thing", config_key="thing.provider",
        )


def test_error_cls_subclass_is_raised():
    class CustomError(ProviderConfigError):
        pass

    with pytest.raises(CustomError):
        instantiate_provider("nope", _BUILTINS, _DefaultWidget, CustomError, what="thing")


def test_load_class_invalid_dotted_path_raises():
    with pytest.raises(ProviderConfigError, match="invalid provider class path"):
        load_class("nodots")


def test_load_class_bad_import_raises():
    with pytest.raises(ProviderConfigError, match="could not be imported"):
        load_class("totally.fake.module.Class")
