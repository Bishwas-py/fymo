"""Build-time enforcement that route-level require_auth is enforceable
(issue #80 phase 2).

A route carrying require_auth with no @identify resolver in app/auth/ can
never let anyone in: every visit redirects to signin and signin itself can
never establish an identity. An unimportable dotted-path guard is worse: it
must fail at build/boot, never at request time. Both fail `fymo build` AND
`fymo dev` (see check_page_auth_hygiene's docstring for why this check is
deliberately not dev-lenient, unlike check_auth_enforcement_hygiene).
"""
import sys
from pathlib import Path

import pytest
import yaml

from fymo.auth.identity import reset_identity_resolvers
from fymo.build.hygiene import check_page_auth_hygiene, format_page_auth_error


RESOLVER = (
    "from fymo.auth import identify, Identity\n"
    "@identify\n"
    "def by_header(event):\n"
    "    uid = event.headers.get('x-user')\n"
    "    return Identity(uid=uid) if uid else None\n"
)

GUARD = (
    "def require_admin():\n"
    "    return None\n"
)


def _scaffold(tmp_path: Path, routes: dict, files: dict | None = None) -> Path:
    (tmp_path / "fymo.yml").write_text(yaml.safe_dump({"routes": routes}))
    for rel, content in (files or {}).items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path


def _cleanup_app_modules() -> None:
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


@pytest.fixture(autouse=True)
def _clean():
    reset_identity_resolvers()
    _cleanup_app_modules()
    yield
    reset_identity_resolvers()
    _cleanup_app_modules()


AUTH_PKG = {"app/__init__.py": "", "app/auth/__init__.py": ""}


def test_no_require_auth_routes_no_violations(tmp_path: Path):
    project = _scaffold(tmp_path, {"root": "index.index", "resources": ["posts"]})
    assert check_page_auth_hygiene(project) == []


def test_no_fymo_yml_no_violations(tmp_path: Path):
    assert check_page_auth_hygiene(tmp_path) == []


def test_require_auth_without_app_auth_dir_violates(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "signin": "signin.index",
        "resources": [{"name": "posts", "require_auth": True}],
    })
    violations = check_page_auth_hygiene(project)
    assert len(violations) == 1
    assert "@identify" in violations[0]
    assert "app/auth/" in violations[0]


def test_require_auth_with_empty_app_auth_violates(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "signin": "signin.index",
        "resources": [{"name": "posts", "require_auth": True}],
    }, {**AUTH_PKG, "app/auth/resolver.py": "def helper():\n    return None\n"})
    violations = check_page_auth_hygiene(project)
    assert len(violations) == 1
    assert "@identify" in violations[0]


def test_require_auth_with_resolver_passes(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "signin": "signin.index",
        "resources": [{"name": "posts", "require_auth": True}],
    }, {**AUTH_PKG, "app/auth/resolver.py": RESOLVER})
    assert check_page_auth_hygiene(project) == []


def test_resolver_registered_outside_project_does_not_count(tmp_path: Path):
    """A resolver registered by some other project (or a stray test) in the
    same process must not satisfy THIS project's check."""
    from fymo.auth import Identity, identify

    @identify
    def stray(event):
        return Identity(uid="stray")

    project = _scaffold(tmp_path, {
        "signin": "signin.index",
        "resources": [{"name": "posts", "require_auth": True}],
    }, AUTH_PKG)
    violations = check_page_auth_hygiene(project)
    assert len(violations) == 1
    assert "@identify" in violations[0]


def test_unimportable_guard_violates_naming_path_and_route(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "signin": "signin.index",
        "settings": {"to": "settings.index", "require_auth": "app.auth.guards.require_admin"},
    }, {**AUTH_PKG, "app/auth/resolver.py": RESOLVER})
    violations = check_page_auth_hygiene(project)
    assert len(violations) == 1
    assert "app.auth.guards.require_admin" in violations[0]
    assert "settings" in violations[0]


def test_importable_guard_passes(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "signin": "signin.index",
        "settings": {"to": "settings.index", "require_auth": "app.auth.guards.require_admin"},
    }, {
        **AUTH_PKG,
        "app/auth/resolver.py": RESOLVER,
        "app/auth/guards.py": GUARD,
    })
    assert check_page_auth_hygiene(project) == []


def test_root_and_resource_require_auth_shapes_are_seen(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "signin": "signin.index",
        "root": {"to": "index.index", "require_auth": True},
    })
    assert len(check_page_auth_hygiene(project)) == 1


def test_signin_route_require_auth_alone_needs_no_resolver(tmp_path: Path):
    """require_auth on the signin route is ignored at boot (auto-public), so
    it alone must not demand a resolver either."""
    project = _scaffold(tmp_path, {
        "signin": {"to": "signin.index", "require_auth": True},
    })
    assert check_page_auth_hygiene(project) == []


def test_format_page_auth_error_lists_violations():
    text = format_page_auth_error(["a violation", "another"])
    assert "a violation" in text
    assert "another" in text


@pytest.mark.parametrize("dev", [False, True])
def test_prepare_build_config_fails_in_build_and_dev(tmp_path: Path, dev: bool):
    """Deliberately not dev-lenient: both entry points refuse."""
    from fymo.build.prepare import BuildError, prepare_build_config

    project = _scaffold(tmp_path, {
        "signin": "signin.index",
        "resources": [{"name": "posts", "require_auth": True}],
    })
    with pytest.raises(BuildError, match="@identify"):
        prepare_build_config(
            project, project / "dist", project / ".fymo" / "entries", dev=dev
        )
