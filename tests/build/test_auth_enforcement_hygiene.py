"""Build-time enforcement that @require_auth is actually enforceable (issue #29).

require_auth itself fails closed correctly: no session means 401, always. The
gap is upstream of that -- nothing stops an app from decorating a remote
function with @require_auth while auth is disabled entirely, or while every
configured provider has declined (required: auto with a missing env var). In
either state nobody can ever authenticate, so the endpoint is either
permanently dead or, in the real case that filed this issue, some app-level
wrapper treats "auth isn't configured" as "must be local dev" and silently
skips the check instead. check_auth_enforcement_hygiene closes the build-time
half of that gap: any @require_auth site plus zero active providers fails the
build, naming the site.
"""
import sys
from pathlib import Path

import pytest

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
    yield
    _cleanup_app_modules()


GUARDED_FN = (
    "from fymo.auth import require_auth\n"
    "@require_auth\n"
    "def create_comment(body: str) -> str: return body\n"
)

UNGUARDED_FN = (
    "def get_posts() -> list: return []\n"
)


def test_no_app_remote_dir_has_no_violations(tmp_path: Path):
    assert check_auth_enforcement_hygiene(tmp_path, {}) == []


def test_no_require_auth_usage_has_no_violations_regardless_of_auth_config(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": UNGUARDED_FN,
    })
    sys.path.insert(0, str(project))
    try:
        assert check_auth_enforcement_hygiene(project, {}) == []
        assert check_auth_enforcement_hygiene(project, {"enabled": False}) == []
    finally:
        sys.path.remove(str(project))


def test_require_auth_with_auth_not_enabled_is_a_violation(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": GUARDED_FN,
    })
    sys.path.insert(0, str(project))
    try:
        violations = check_auth_enforcement_hygiene(project, {})
    finally:
        sys.path.remove(str(project))

    assert len(violations) == 1
    assert "app/remote/posts.py" in violations[0]
    assert "create_comment" in violations[0]


def test_require_auth_with_auth_enabled_and_zero_providers_is_a_violation(tmp_path: Path):
    """required: auto on the only configured provider, declined because its
    env var isn't set -- resolves to an empty provider list at build time,
    the exact real-world shape from the issue."""
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": GUARDED_FN,
    })
    sys.path.insert(0, str(project))
    try:
        auth_config = {
            "enabled": True,
            "providers": [{
                "class": "tests.auth.test_providers.AlwaysUnconfiguredProvider",
                "required": "auto",
            }],
        }
        violations = check_auth_enforcement_hygiene(project, auth_config)
    finally:
        sys.path.remove(str(project))

    assert len(violations) == 1
    assert "create_comment" in violations[0]


def test_require_auth_with_auth_enabled_and_a_real_provider_has_no_violations(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": GUARDED_FN,
    })
    sys.path.insert(0, str(project))
    try:
        violations = check_auth_enforcement_hygiene(project, {"enabled": True})
    finally:
        sys.path.remove(str(project))

    assert violations == []


def test_require_auth_defaults_to_password_provider_when_providers_unset(tmp_path: Path):
    """build_providers([]) defaults to [PasswordProvider()] -- auth.enabled
    true with no providers: key at all must resolve the same way here."""
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": GUARDED_FN,
    })
    sys.path.insert(0, str(project))
    try:
        violations = check_auth_enforcement_hygiene(project, {"enabled": True, "providers": []})
    finally:
        sys.path.remove(str(project))

    assert violations == []


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
        violations = check_auth_enforcement_hygiene(project, {})
    finally:
        sys.path.remove(str(project))

    assert len(violations) == 2
    joined = "\n".join(violations)
    assert "create_comment" in joined
    assert "add_like" in joined


def test_format_auth_enforcement_error_names_the_sites():
    msg = format_auth_enforcement_error([
        "app/remote/posts.py: create_comment requires auth.enabled but auth is off"
    ])
    assert "create_comment" in msg
    assert "app/remote/posts.py" in msg
