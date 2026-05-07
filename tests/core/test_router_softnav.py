"""Router YAML parsing of dict-form resources with `soft_nav: false`."""
from pathlib import Path
import pytest
import yaml

from fymo.core.exceptions import ConfigurationError
from fymo.core.router import Router


def _write_yaml(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "fymo.yml"
    p.write_text(yaml.safe_dump(data))
    return p


def test_string_resources_default_soft_nav_on(tmp_path: Path):
    cfg = _write_yaml(tmp_path, {"routes": {"resources": ["posts", "tags"]}})
    r = Router(cfg)
    assert r.soft_nav_enabled("posts") is True
    assert r.soft_nav_enabled("tags") is True
    assert r.disabled_soft_nav_resources() == []


def test_dict_form_can_disable_soft_nav(tmp_path: Path):
    cfg = _write_yaml(tmp_path, {"routes": {"resources": [
        "posts",
        {"name": "admin", "soft_nav": False},
        {"name": "api_keys", "soft_nav": False},
    ]}})
    r = Router(cfg)
    assert r.soft_nav_enabled("posts") is True
    assert r.soft_nav_enabled("admin") is False
    assert r.soft_nav_enabled("api_keys") is False
    assert r.disabled_soft_nav_resources() == ["admin", "api_keys"]
    # The resource itself is still routable — only soft-nav is disabled.
    assert r.match("/admin") is not None
    assert r.match("/admin")["controller"] == "admin"


def test_dict_form_explicit_soft_nav_true(tmp_path: Path):
    cfg = _write_yaml(tmp_path, {"routes": {"resources": [
        {"name": "posts", "soft_nav": True},
    ]}})
    r = Router(cfg)
    assert r.soft_nav_enabled("posts") is True
    assert r.disabled_soft_nav_resources() == []


def test_dict_resource_missing_name_raises(tmp_path: Path):
    cfg = _write_yaml(tmp_path, {"routes": {"resources": [{"soft_nav": False}]}})
    with pytest.raises(ConfigurationError, match="missing required 'name'"):
        Router(cfg)


def test_invalid_resource_type_raises(tmp_path: Path):
    cfg = _write_yaml(tmp_path, {"routes": {"resources": [42]}})
    with pytest.raises(ConfigurationError, match="must be a string or dict"):
        Router(cfg)


def test_unknown_controller_defaults_enabled(tmp_path: Path):
    """Asking about a controller never declared in fymo.yml returns True."""
    cfg = _write_yaml(tmp_path, {"routes": {"resources": ["posts"]}})
    r = Router(cfg)
    assert r.soft_nav_enabled("nonexistent") is True
