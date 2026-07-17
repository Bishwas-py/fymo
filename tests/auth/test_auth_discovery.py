"""app/auth/ auto-discovery (issue #80 phase 2).

Importing app/auth/*.py is what turns the new identity system on: each
module body runs and its @identify decorators self-register. No config key
gates it; deleting the directory turns it off. Mirrors how app/remote/,
app/jobs/, and app/broadcasts/ modules are walked (sys.path insert/remove,
parent-package eviction, evict + fresh import), but collects nothing.
"""
import sys
from pathlib import Path

import pytest

from fymo.auth.discovery import import_auth_modules
from fymo.auth.identity import (
    registered_identity_resolvers,
    reset_identity_resolvers,
)


RESOLVER = (
    "from fymo.auth import identify, Identity\n"
    "@identify\n"
    "def by_header(event):\n"
    "    if event.headers.get('x-user'):\n"
    "        return Identity(uid=event.headers['x-user'])\n"
    "    return None\n"
)


def _scaffold(tmp_path: Path, files: dict) -> Path:
    for rel, content in files.items():
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


def test_no_app_auth_dir_imports_nothing(tmp_path: Path):
    assert import_auth_modules(tmp_path) == []
    assert registered_identity_resolvers() == ()


def test_importing_app_auth_registers_resolvers(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/auth/__init__.py": "",
        "app/auth/resolver.py": RESOLVER,
    })
    assert import_auth_modules(project) == ["app.auth.resolver"]
    assert len(registered_identity_resolvers()) == 1


def test_modules_import_in_sorted_order(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/auth/__init__.py": "",
        "app/auth/b_second.py": RESOLVER,
        "app/auth/a_first.py": RESOLVER.replace("by_header", "by_cookie"),
    })
    assert import_auth_modules(project) == [
        "app.auth.a_first",
        "app.auth.b_second",
    ]
    assert len(registered_identity_resolvers()) == 2


def test_private_modules_and_init_are_skipped(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/auth/__init__.py": "",
        "app/auth/_helpers.py": RESOLVER,
    })
    assert import_auth_modules(project) == []
    assert registered_identity_resolvers() == ()


def test_reimport_dedupes_by_definition_site(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/auth/__init__.py": "",
        "app/auth/resolver.py": RESOLVER,
    })
    import_auth_modules(project)
    import_auth_modules(project)
    assert len(registered_identity_resolvers()) == 1


def test_sys_path_restored_after_import(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/auth/__init__.py": "",
        "app/auth/resolver.py": RESOLVER,
    })
    before = list(sys.path)
    import_auth_modules(project)
    assert sys.path == before


def test_app_remote_modules_are_not_imported(tmp_path: Path):
    """app/auth discovery must never execute app/remote code (and vice
    versa, covered below): the two directories are separate seams."""
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/auth/__init__.py": "",
        "app/auth/resolver.py": RESOLVER,
        "app/remote/__init__.py": "",
        "app/remote/api.py": RESOLVER.replace("by_header", "smuggled"),
    })
    import_auth_modules(project)
    assert "app.remote.api" not in sys.modules
    assert len(registered_identity_resolvers()) == 1


def test_remote_discovery_does_not_scan_app_auth(tmp_path: Path):
    """app/auth modules are backend code but NOT remote modules: they must
    never be scanned for @remote exposure or emitted to the client."""
    from fymo.remote.discovery import discover_remote_modules

    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/auth/__init__.py": "",
        "app/auth/resolver.py": (
            "def looks_remote(name: str) -> str:\n"
            "    return name\n"
        ),
        "app/remote/__init__.py": "",
        "app/remote/api.py": "def ping() -> str:\n    return 'pong'\n",
    })
    sys.path.insert(0, str(project))
    try:
        modules = discover_remote_modules(project)
    finally:
        sys.path.remove(str(project))
    assert set(modules) == {"api"}
    assert "app.auth.resolver" not in sys.modules


def test_stale_resolvers_from_another_project_are_pruned(tmp_path_factory):
    """Two projects in one process (the test-session reality): importing
    project B's app/auth must drop resolvers whose defining file lives in
    project A, mirroring the app.* sys.modules eviction FymoApp does."""
    root_a = _scaffold(tmp_path_factory.mktemp("proj_a"), {
        "app/__init__.py": "",
        "app/auth/__init__.py": "",
        "app/auth/resolver.py": RESOLVER,
    })
    root_b = _scaffold(tmp_path_factory.mktemp("proj_b"), {
        "app/__init__.py": "",
        "app/auth/__init__.py": "",
        "app/auth/resolver.py": RESOLVER.replace("'x-user'", "'x-other'").replace("['x-user']", "['x-other']"),
    })
    import_auth_modules(root_a)
    _cleanup_app_modules()
    import_auth_modules(root_b)
    resolvers = registered_identity_resolvers()
    assert len(resolvers) == 1
    resolver_file = Path(resolvers[0].__code__.co_filename).resolve()
    assert resolver_file.is_relative_to(root_b.resolve())
