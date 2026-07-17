"""Route-level require_auth for page loads (issue #80 phase 2).

Covers the whole seam without a Node sidecar: Router parsing of the one new
route attribute, the signin conventions (auto-public target, hard error when
missing), boot-time guard import validation, the page_auth_redirect check
itself, and enforcement placement in both page-serving paths (full-page SSR
via TemplateRenderer, soft-nav via handle_data) before any render work.
"""
import io
import json
import sys
import types
from pathlib import Path

import pytest
import yaml

from fymo.auth import Identity, identify
from fymo.auth.identity import reset_identity_resolvers
from fymo.core.exceptions import ConfigurationError
from fymo.core.page_auth import (
    REQUIRE_AUTH_WITHOUT_SIGNIN_ERROR,
    page_auth_redirect,
    validate_route_guards,
)
from fymo.core.router import Router
from fymo.remote.identity import set_secret


@pytest.fixture(autouse=True)
def _clean_identity():
    set_secret(b"x" * 32)
    reset_identity_resolvers()
    yield
    reset_identity_resolvers()


def _write_yaml(tmp_path: Path, routes: dict) -> Path:
    p = tmp_path / "fymo.yml"
    p.write_text(yaml.safe_dump({"routes": routes}))
    return p


def _environ(path: str, query: str = "", headers: dict | None = None) -> dict:
    env = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(b""),
        "wsgi.errors": sys.stderr,
        "wsgi.url_scheme": "http",
    }
    for name, value in (headers or {}).items():
        env["HTTP_" + name.upper().replace("-", "_")] = value
    return env


def _register_header_resolver():
    @identify
    def by_header(event):
        uid = event.headers.get("x-user")
        return Identity(uid=uid) if uid else None


# --------------- Router parsing ---------------


def test_resource_require_auth_attaches_to_expanded_routes(tmp_path: Path):
    cfg = _write_yaml(tmp_path, {
        "resources": [{"name": "posts", "require_auth": True}, "tags"],
        "signin": "signin.index",
    })
    r = Router(cfg)
    for path in ("/posts", "/posts/new", "/posts/1", "/posts/1/edit"):
        assert r.match(path).get("require_auth") is True, path
    assert r.match("/tags").get("require_auth") is None


def test_explicit_route_dict_to_form_with_require_auth(tmp_path: Path):
    cfg = _write_yaml(tmp_path, {
        "dashboard": {"to": "dashboard.index", "require_auth": True},
        "signin": "signin.index",
    })
    r = Router(cfg)
    info = r.match("/dashboard")
    assert info["controller"] == "dashboard"
    assert info["action"] == "index"
    assert info["template"] == "dashboard/index.svelte"
    assert info["require_auth"] is True


def test_explicit_route_dotted_guard_value(tmp_path: Path):
    cfg = _write_yaml(tmp_path, {
        "settings": {"to": "settings.index", "require_auth": "app.auth.guards.require_admin"},
        "signin": "signin.index",
    })
    r = Router(cfg)
    assert r.match("/settings")["require_auth"] == "app.auth.guards.require_admin"


def test_root_dict_form_with_require_auth(tmp_path: Path):
    cfg = _write_yaml(tmp_path, {
        "root": {"to": "index.index", "require_auth": True},
        "signin": "signin.index",
    })
    r = Router(cfg)
    info = r.match("/")
    assert info["controller"] == "index"
    assert info["require_auth"] is True


def test_root_string_form_still_works(tmp_path: Path):
    cfg = _write_yaml(tmp_path, {"root": "index.index"})
    r = Router(cfg)
    info = r.match("/")
    assert info["controller"] == "index"
    assert info.get("require_auth") is None


def test_routes_without_require_auth_are_public(tmp_path: Path):
    cfg = _write_yaml(tmp_path, {"root": "index.index", "resources": ["posts"]})
    r = Router(cfg)
    assert r.match("/posts").get("require_auth") is None
    assert r.signin_path() is None


def test_require_auth_without_signin_route_raises(tmp_path: Path):
    cfg = _write_yaml(tmp_path, {
        "resources": [{"name": "posts", "require_auth": True}],
    })
    with pytest.raises(ConfigurationError, match="signin"):
        Router(cfg)


def test_signin_path_from_explicit_route(tmp_path: Path):
    cfg = _write_yaml(tmp_path, {
        "signin": "signin.index",
        "resources": [{"name": "posts", "require_auth": True}],
    })
    assert Router(cfg).signin_path() == "/signin"


def test_signin_path_from_resource(tmp_path: Path):
    cfg = _write_yaml(tmp_path, {
        "resources": ["signin", {"name": "posts", "require_auth": True}],
    })
    assert Router(cfg).signin_path() == "/signin"


def test_signin_route_require_auth_ignored_with_warning(tmp_path: Path, capsys):
    cfg = _write_yaml(tmp_path, {
        "signin": {"to": "signin.index", "require_auth": True},
        "resources": [{"name": "posts", "require_auth": True}],
    })
    r = Router(cfg)
    assert r.match("/signin").get("require_auth") is None
    out = capsys.readouterr().out
    assert "signin" in out


def test_convention_alias_inherits_require_auth_from_explicit_route(tmp_path: Path):
    """A convention-based alias resolving to a controller that has a declared
    protected route must inherit the protection, else it renders the same
    manifest anonymously."""
    cfg = _write_yaml(tmp_path, {
        "dashboard": {"to": "dashboard.index", "require_auth": True},
        "signin": "signin.index",
    })
    r = Router(cfg)
    assert r.match("/dashboard")["require_auth"] is True
    # /dashboard/index and /dashboard/anything are convention guesses that the
    # manifest still keys by the dashboard controller.
    assert r.match("/dashboard/index").get("convention") is True
    assert r.match("/dashboard/index")["require_auth"] is True
    assert r.match("/dashboard/whatever")["require_auth"] is True


def test_convention_alias_inherits_from_protected_root(tmp_path: Path):
    cfg = _write_yaml(tmp_path, {
        "root": {"to": "home.index", "require_auth": True},
        "signin": "signin.index",
    })
    r = Router(cfg)
    assert r.match("/home").get("convention") is True
    assert r.match("/home")["require_auth"] is True
    assert r.match("/home/index")["require_auth"] is True


def test_convention_alias_of_public_controller_stays_public(tmp_path: Path):
    cfg = _write_yaml(tmp_path, {
        "root": "home.index",
        "resources": ["tags"],
    })
    r = Router(cfg)
    assert r.match("/tags/whatever").get("require_auth") is None
    assert r.match("/home/whatever").get("require_auth") is None


def test_convention_inheritance_most_restrictive_guard_wins_over_bool(tmp_path: Path):
    """When declared routes for one controller mix `true` and a guard path,
    the guard wins (it implies signed-in AND more)."""
    cfg = _write_yaml(tmp_path, {
        "dash": {"to": "dash.index", "require_auth": True},
        "dash_admin": {"to": "dash.admin", "require_auth": "app.auth.guards.require_admin"},
        "signin": "signin.index",
    })
    r = Router(cfg)
    assert r.match("/dash/anything")["require_auth"] == "app.auth.guards.require_admin"


def test_convention_inheritance_conflicting_guards_first_declared_wins(tmp_path: Path):
    cfg = _write_yaml(tmp_path, {
        "a": {"to": "dash.index", "require_auth": "app.auth.guards.first"},
        "b": {"to": "dash.admin", "require_auth": "app.auth.guards.second"},
        "signin": "signin.index",
    })
    r = Router(cfg)
    assert r.match("/dash/anything")["require_auth"] == "app.auth.guards.first"


def test_signin_target_not_protected_by_its_own_route(tmp_path: Path):
    """signin: home.index is auto-public; on its own it must not protect the
    home controller's convention aliases."""
    cfg = _write_yaml(tmp_path, {
        "signin": "home.index",
        "resources": [{"name": "posts", "require_auth": True}],
    })
    r = Router(cfg)
    assert r.match("/home/whatever").get("require_auth") is None


def test_declared_signin_path_public_even_when_controller_shared_with_protected(tmp_path: Path):
    """root and signin both target home.index: the home controller is protected
    via root, aliases inherit it, but the exact /signin path stays public."""
    cfg = _write_yaml(tmp_path, {
        "root": {"to": "home.index", "require_auth": True},
        "signin": "home.index",
    })
    r = Router(cfg)
    assert r.match("/signin").get("require_auth") is None
    assert r.match("/home")["require_auth"] is True
    assert r.match("/home/index")["require_auth"] is True


def test_unknown_route_keys_keep_todays_behavior(tmp_path: Path):
    """No `public:`/`on_unauthenticated:` attributes exist; unknown keys in a
    dict route ride along in route info and are ignored, exactly as today."""
    cfg = _write_yaml(tmp_path, {
        "dashboard": {"to": "dashboard.index", "public": True},
    })
    r = Router(cfg)
    info = r.match("/dashboard")
    assert info.get("require_auth") is None
    assert info.get("public") is True


# --------------- boot-time guard validation ---------------


def _fake_guard_module(monkeypatch, name="fake_guards", **attrs):
    mod = types.ModuleType(name)
    for attr, value in attrs.items():
        setattr(mod, attr, value)
    monkeypatch.setitem(sys.modules, name, mod)
    return mod


def _router_with(tmp_path, routes):
    return Router(_write_yaml(tmp_path, routes))


def test_validate_route_guards_accepts_true_and_importable_guards(tmp_path, monkeypatch):
    _fake_guard_module(monkeypatch, require_admin=lambda: None)
    r = _router_with(tmp_path, {
        "signin": "signin.index",
        "dashboard": {"to": "dashboard.index", "require_auth": True},
        "settings": {"to": "settings.index", "require_auth": "fake_guards.require_admin"},
    })
    validate_route_guards(r)


def test_validate_route_guards_raises_for_unimportable_module(tmp_path):
    r = _router_with(tmp_path, {
        "signin": "signin.index",
        "settings": {"to": "settings.index", "require_auth": "no.such.module.guard"},
    })
    with pytest.raises(ConfigurationError, match=r"no\.such\.module\.guard") as exc_info:
        validate_route_guards(r)
    assert "/settings" in str(exc_info.value)


def test_validate_route_guards_raises_for_missing_attr(tmp_path, monkeypatch):
    _fake_guard_module(monkeypatch, require_admin=lambda: None)
    r = _router_with(tmp_path, {
        "signin": "signin.index",
        "settings": {"to": "settings.index", "require_auth": "fake_guards.nope"},
    })
    with pytest.raises(ConfigurationError, match=r"fake_guards\.nope"):
        validate_route_guards(r)


def test_validate_route_guards_rejects_non_bool_non_str(tmp_path):
    r = _router_with(tmp_path, {
        "signin": "signin.index",
        "settings": {"to": "settings.index", "require_auth": 7},
    })
    with pytest.raises(ConfigurationError, match="require_auth"):
        validate_route_guards(r)


# --------------- page_auth_redirect ---------------


def test_anonymous_redirects_to_signin_with_next():
    location = page_auth_redirect(True, _environ("/todos"), "/signin", "/todos")
    assert location == "/signin?next=%2Ftodos"


def test_query_string_carried_in_next():
    env = _environ("/todos", query="page=2&sort=asc")
    location = page_auth_redirect(True, env, "/signin", "/todos")
    assert location == "/signin?next=%2Ftodos%3Fpage%3D2%26sort%3Dasc"


def test_signed_in_true_passes():
    _register_header_resolver()
    env = _environ("/todos", headers={"x-user": "u1"})
    assert page_auth_redirect(True, env, "/signin", "/todos") is None


def test_missing_environ_fails_closed():
    _register_header_resolver()
    assert page_auth_redirect(True, None, "/signin", "/todos") == "/signin?next=%2Ftodos"


def test_guard_pass_allows_request(monkeypatch):
    _register_header_resolver()
    _fake_guard_module(monkeypatch, require_admin=lambda: None)
    env = _environ("/settings", headers={"x-user": "admin"})
    assert page_auth_redirect("fake_guards.require_admin", env, "/signin", "/settings") is None


def test_guard_exception_redirects(monkeypatch):
    _register_header_resolver()

    def deny():
        raise ValueError("not an admin")

    _fake_guard_module(monkeypatch, require_admin=deny)
    env = _environ("/settings", headers={"x-user": "u1"})
    location = page_auth_redirect("fake_guards.require_admin", env, "/signin", "/settings")
    assert location == "/signin?next=%2Fsettings"


def test_anon_never_reaches_guard(monkeypatch):
    _register_header_resolver()
    calls = []

    def guard():
        calls.append(1)

    _fake_guard_module(monkeypatch, require_admin=guard)
    env = _environ("/settings")
    location = page_auth_redirect("fake_guards.require_admin", env, "/signin", "/settings")
    assert location == "/signin?next=%2Fsettings"
    assert calls == []


def test_guard_runs_inside_request_scope(monkeypatch):
    _register_header_resolver()
    seen = {}

    def guard():
        from fymo.auth import current_uid
        seen["uid"] = current_uid()

    _fake_guard_module(monkeypatch, require_admin=guard)
    env = _environ("/settings", headers={"x-user": "u42"})
    assert page_auth_redirect("fake_guards.require_admin", env, "/signin", "/settings") is None
    assert seen == {"uid": "u42"}


# --------------- full-page SSR enforcement placement ---------------


def _make_renderer(tmp_path: Path, routes: dict):
    from fymo.core.assets import AssetManager
    from fymo.core.config import ConfigManager
    from fymo.core.template_renderer import TemplateRenderer

    router = Router(_write_yaml(tmp_path, routes))
    return TemplateRenderer(
        tmp_path, ConfigManager(tmp_path, {}), AssetManager(tmp_path), router, dev=True
    )


PROTECTED_ROUTES = {
    "signin": "signin.index",
    "resources": [{"name": "todos", "require_auth": True}],
}


def test_protected_page_anon_gets_302_before_any_render(tmp_path: Path):
    """manifest_cache is None here on purpose: touching it would raise, so a
    302 proves enforcement fired before any manifest/sidecar work."""
    r = _make_renderer(tmp_path, PROTECTED_ROUTES)
    html, status, headers = r.render_template("/todos", _environ("/todos"))
    assert status.startswith("302")
    assert dict(headers)["Location"] == "/signin?next=%2Ftodos"
    assert html == ""


def test_protected_page_signed_in_proceeds_to_render(tmp_path: Path):
    _register_header_resolver()
    r = _make_renderer(tmp_path, PROTECTED_ROUTES)
    env = _environ("/todos", headers={"x-user": "u1"})
    _, status, headers = r.render_template("/todos", env)
    assert not status.startswith("302")
    assert "Location" not in dict(headers)


def test_public_page_unaffected(tmp_path: Path):
    r = _make_renderer(tmp_path, {
        "signin": "signin.index",
        "resources": ["tags", {"name": "todos", "require_auth": True}],
    })
    _, status, headers = r.render_template("/tags", _environ("/tags"))
    assert not status.startswith("302")


# --------------- soft-nav enforcement placement ---------------


class _FakeApp:
    def __init__(self, router):
        self.router = router
        self.dev = True
        self.manifest_cache = None


def _soft_nav_get(app, path: str, headers: dict | None = None):
    from fymo.core.soft_nav import handle_data

    responses = []

    def sr(status, hdrs):
        responses.append((status, hdrs))

    env = _environ(path, headers=headers)
    body = b"".join(handle_data(app, env, sr))
    return responses[0], json.loads(body)


def test_soft_nav_protected_route_anon_gets_redirect_envelope(tmp_path: Path):
    router = Router(_write_yaml(tmp_path, PROTECTED_ROUTES))
    (status, _), envelope = _soft_nav_get(_FakeApp(router), "/_fymo/data/todos")
    assert status.startswith("200")
    assert envelope == {
        "type": "redirect",
        "location": "/signin?next=%2Ftodos",
        "status": 302,
    }
