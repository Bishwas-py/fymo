"""Build-time enforcement that @require_auth is actually enforceable.

require_auth itself fails closed correctly: no resolved identity means
401, always. The gap is upstream of that: nothing stops an app from
decorating a remote function with @require_auth while app/auth/ registers
zero @identify resolvers, and in that state nobody can ever authenticate,
so the endpoint is either permanently dead or invites app code to route
around the guard. check_auth_enforcement_hygiene closes the build-time
half of that gap: any @require_auth site plus zero registered resolvers
fails the build, naming the site.
"""
import sys
from pathlib import Path

import pytest

from fymo.auth.identity import reset_identity_resolvers
from fymo.build.hygiene import check_auth_enforcement_hygiene, format_auth_enforcement_error


def _scaffold(tmp_path: Path, files: dict[str, str]) -> Path:
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
def _cleanup():
    reset_identity_resolvers()
    yield
    reset_identity_resolvers()
    _cleanup_app_modules()


GUARDED_FN = (
    "from fymo.auth import require_auth\n"
    "@require_auth\n"
    "def create_comment(body: str) -> str: return body\n"
)

UNGUARDED_FN = (
    "def get_posts() -> list: return []\n"
)

RESOLVER_MODULE = (
    "from fymo.auth import Identity, identify\n"
    "@identify\n"
    "def by_header(event):\n"
    "    uid = event.headers.get('x-user')\n"
    "    return Identity(uid=uid) if uid else None\n"
)


def test_no_app_remote_dir_has_no_violations(tmp_path: Path):
    assert check_auth_enforcement_hygiene(tmp_path) == []


def test_no_require_auth_usage_has_no_violations(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": UNGUARDED_FN,
    })
    sys.path.insert(0, str(project))
    try:
        assert check_auth_enforcement_hygiene(project) == []
    finally:
        sys.path.remove(str(project))


def test_require_auth_with_no_resolvers_is_a_violation(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": GUARDED_FN,
    })
    sys.path.insert(0, str(project))
    try:
        violations = check_auth_enforcement_hygiene(project)
    finally:
        sys.path.remove(str(project))

    assert len(violations) == 1
    assert "app/remote/posts.py" in violations[0]
    assert "create_comment" in violations[0]
    assert "@identify" in violations[0]


def test_require_auth_with_a_registered_resolver_has_no_violations(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/auth/__init__.py": "",
        "app/auth/resolver.py": RESOLVER_MODULE,
        "app/remote/__init__.py": "",
        "app/remote/posts.py": GUARDED_FN,
    })
    sys.path.insert(0, str(project))
    try:
        violations = check_auth_enforcement_hygiene(project)
    finally:
        sys.path.remove(str(project))

    assert violations == []


def test_resolver_from_another_project_does_not_satisfy_the_check(tmp_path: Path):
    """The registry is process-global: a resolver defined outside this
    project root (another project loaded earlier, a test helper) must not
    make this project's @require_auth sites pass."""
    from fymo.auth import Identity, identify

    @identify
    def foreign(event):
        return Identity(uid="u_foreign")

    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": GUARDED_FN,
    })
    sys.path.insert(0, str(project))
    try:
        violations = check_auth_enforcement_hygiene(project)
    finally:
        sys.path.remove(str(project))

    assert len(violations) == 1
    assert "create_comment" in violations[0]


def test_multiple_guarded_functions_across_modules_all_reported(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": GUARDED_FN,
        "app/remote/likes.py": (
            "from fymo.auth import require_auth\n"
            "@require_auth\n"
            "def add_like(slug: str) -> str: return slug\n"
        ),
    })
    sys.path.insert(0, str(project))
    try:
        violations = check_auth_enforcement_hygiene(project)
    finally:
        sys.path.remove(str(project))

    assert len(violations) == 2
    joined = "\n".join(violations)
    assert "create_comment" in joined
    assert "add_like" in joined


def test_format_auth_enforcement_error_names_the_sites_and_the_fix():
    msg = format_auth_enforcement_error([
        "app/remote/posts.py: create_comment is decorated with @require_auth "
        "but app/auth/ registers no @identify resolver"
    ])
    assert "create_comment" in msg
    assert "app/remote/posts.py" in msg
    assert "fymo generate auth" in msg
