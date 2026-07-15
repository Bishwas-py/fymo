"""Build-time enforcement of explicit remote exposure (issue #8).

File placement alone in app/remote/*.py used to be a security decision:
every public typed top-level function was browser-callable by default. A
real app got this wrong: an internal storage helper sat next to real
endpoints with no auth guard and turned out to be callable over the wire.

`remote.explicit_optin` already lets a project require `@remote` on
anything it wants exposed (see fymo/remote/decorators.py and
discovery.is_exposed_remote_fn), but with the flag left at its default
(False) nothing told a developer they were shipping implicit exposure.
This module's check closes that gap: when explicit_optin is off, the build
fails and names every function that IS exposed under implicit mode but
carries no `@remote` marker, so a developer can mark it or move it before
it ships. `remote.allow_implicit: true` is the documented-unsafe escape
hatch for apps not ready to migrate.
"""
import sys
from pathlib import Path

import pytest

from fymo.core.exceptions import ConfigurationError
from fymo.build.hygiene import check_remote_exposure_hygiene, format_remote_exposure_error
from fymo.remote.mode import RemoteModeConfigError


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


MARKED_AND_UNMARKED = (
    "from fymo.remote import remote\n"
    "@remote\n"
    "def get_posts() -> list: return []\n"
    "def insert_version(x: str) -> str: return x\n"
)

ALL_MARKED = (
    "from fymo.remote import remote\n"
    "@remote\n"
    "def get_posts() -> list: return []\n"
    "@remote\n"
    "def get_post(slug: str) -> dict: return {}\n"
)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    _cleanup_app_modules()


def test_no_app_remote_dir_has_no_violations(tmp_path: Path):
    assert check_remote_exposure_hygiene(tmp_path, {}) == []


def test_unmarked_function_is_a_violation_under_default_config(tmp_path: Path):
    """explicit_optin defaults to False and allow_implicit is unset: the
    permissive-but-unsafe combination this check exists to catch."""
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/versions.py": MARKED_AND_UNMARKED,
    })
    sys.path.insert(0, str(project))
    try:
        violations = check_remote_exposure_hygiene(project, {})
    finally:
        sys.path.remove(str(project))

    assert len(violations) == 1
    assert "app/remote/versions.py" in violations[0]
    assert "insert_version" in violations[0]
    assert "get_posts" not in violations[0]


def test_all_marked_functions_have_no_violations(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": ALL_MARKED,
    })
    sys.path.insert(0, str(project))
    try:
        violations = check_remote_exposure_hygiene(project, {})
    finally:
        sys.path.remove(str(project))

    assert violations == []


def test_allow_implicit_escape_hatch_silences_the_check(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/versions.py": MARKED_AND_UNMARKED,
    })
    sys.path.insert(0, str(project))
    try:
        violations = check_remote_exposure_hygiene(project, {"allow_implicit": True})
    finally:
        sys.path.remove(str(project))

    assert violations == []


def test_explicit_optin_true_skips_the_check_entirely(tmp_path: Path):
    """When explicit_optin is on, an unmarked function is simply not exposed
    (private helper): there's nothing to warn about in this mode."""
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/versions.py": MARKED_AND_UNMARKED,
    })
    sys.path.insert(0, str(project))
    try:
        violations = check_remote_exposure_hygiene(project, {"explicit_optin": True})
    finally:
        sys.path.remove(str(project))

    assert violations == []


def test_mode_strict_skips_the_check_entirely(tmp_path: Path):
    """remote.mode: strict must resolve to the same hygiene_enforced=False as
    explicit_optin: true: dispatch is already gated, so there's nothing
    silently exposed to warn about."""
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/versions.py": MARKED_AND_UNMARKED,
    })
    sys.path.insert(0, str(project))
    try:
        violations = check_remote_exposure_hygiene(project, {"mode": "strict"})
    finally:
        sys.path.remove(str(project))

    assert violations == []


def test_mode_implicit_legacy_skips_the_check_entirely(tmp_path: Path):
    """remote.mode: implicit-legacy is the new spelling of allow_implicit:
    true, the acknowledged-unsafe escape hatch."""
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/versions.py": MARKED_AND_UNMARKED,
    })
    sys.path.insert(0, str(project))
    try:
        violations = check_remote_exposure_hygiene(project, {"mode": "implicit-legacy"})
    finally:
        sys.path.remove(str(project))

    assert violations == []


def test_invalid_mode_raises_remote_mode_config_error(tmp_path: Path):
    """An unresolvable remote.mode must surface as RemoteModeConfigError, not
    a silent [] or a hygiene violation list. Wrapping into a BuildError is
    the caller's job (fymo/build/prepare.py), not this function's."""
    with pytest.raises(RemoteModeConfigError, match="bogus"):
        check_remote_exposure_hygiene(tmp_path, {"mode": "bogus"})


def test_multiple_unmarked_functions_across_modules_all_reported(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/versions.py": MARKED_AND_UNMARKED,
        "app/remote/jobs.py": "def run_job(id: str) -> str: return id\n",
    })
    sys.path.insert(0, str(project))
    try:
        violations = check_remote_exposure_hygiene(project, {})
    finally:
        sys.path.remove(str(project))

    assert len(violations) == 2
    joined = "\n".join(violations)
    assert "insert_version" in joined
    assert "run_job" in joined


def test_underscore_prefixed_helpers_are_not_flagged(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/versions.py": (
            "def _private_helper(x: str) -> str: return x\n"
        ),
    })
    sys.path.insert(0, str(project))
    try:
        violations = check_remote_exposure_hygiene(project, {})
    finally:
        sys.path.remove(str(project))

    assert violations == []


def test_format_remote_exposure_error_names_the_functions():
    msg = format_remote_exposure_error([
        "app/remote/versions.py: insert_version is browser-callable "
        "but has no @remote marker"
    ])
    assert "insert_version" in msg
    assert "app/remote/versions.py" in msg
    assert "implicit-legacy" in msg


def test_explicit_optin_string_false_from_interpolation_does_not_skip_the_check(tmp_path: Path):
    """Regression for issue #30: a bare truthy check on an interpolated
    remote.explicit_optin: ${VAR} would treat the resolved string "false"
    as on and silently skip this check, the opposite of what was asked."""
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/versions.py": MARKED_AND_UNMARKED,
    })
    sys.path.insert(0, str(project))
    try:
        violations = check_remote_exposure_hygiene(project, {"explicit_optin": "false"})
    finally:
        sys.path.remove(str(project))

    assert len(violations) == 1
    assert "insert_version" in violations[0]


def test_allow_implicit_string_false_from_interpolation_does_not_skip_the_check(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/versions.py": MARKED_AND_UNMARKED,
    })
    sys.path.insert(0, str(project))
    try:
        violations = check_remote_exposure_hygiene(project, {"allow_implicit": "false"})
    finally:
        sys.path.remove(str(project))

    assert len(violations) == 1
    assert "insert_version" in violations[0]


def test_raises_configuration_error_on_garbage_explicit_optin(tmp_path: Path):
    with pytest.raises(ConfigurationError, match="remote.explicit_optin"):
        check_remote_exposure_hygiene(tmp_path, {"explicit_optin": "enabeld"})
