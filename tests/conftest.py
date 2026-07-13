"""Shared pytest fixtures for fymo tests."""
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_APP = REPO_ROOT / "examples" / "todo_app"
BLOG_APP = REPO_ROOT / "examples" / "blog_app"
VENV_BIN = Path(sys.executable).parent


@pytest.fixture(autouse=True, scope="session")
def _prepend_venv_bin_to_path() -> None:
    """Ensure the active venv's bin/ is first on PATH so subprocess calls to
    `fymo` resolve to the same installation as the test runner."""
    current_path = os.environ.get("PATH", "")
    venv_bin_str = str(VENV_BIN)
    if not current_path.startswith(venv_bin_str):
        os.environ["PATH"] = venv_bin_str + os.pathsep + current_path


@pytest.fixture(autouse=True, scope="session")
def _fymo_secret_for_tests() -> None:
    """Provide FYMO_SECRET so FymoApp instances created in tests don't have to
    each set dev=True or maintain a per-project .fymo/secret.key file."""
    os.environ.setdefault("FYMO_SECRET", "test-secret-please-do-not-use-in-prod-32b!")


@pytest.fixture
def example_app(tmp_path: Path) -> Path:
    """Copy of examples/todo_app into an isolated tmp dir.

    node_modules is symlinked (not copied) from the original to keep fixture
    setup fast. Treat it as read-only — tests must not write into it, since
    the symlink target is shared across all test runs and the developer's
    working copy.
    """
    dest = tmp_path / "todo_app"
    shutil.copytree(EXAMPLE_APP, dest, ignore=shutil.ignore_patterns("node_modules", "dist", ".fymo"))
    nm = EXAMPLE_APP / "node_modules"
    if nm.is_dir():
        (dest / "node_modules").symlink_to(nm)
    else:
        pytest.skip("examples/todo_app/node_modules not found — run npm install in examples/todo_app/")
    return dest


@pytest.fixture
def blog_app(tmp_path: Path) -> Path:
    """Copy of examples/blog_app into an isolated tmp dir.

    Unlike todo_app, this example has real app/remote/*.py functions and
    auth enabled — needed for tests that exercise remote-module discovery
    (todo_app has neither). Same node_modules-symlink treatment as
    example_app: read-only, shared across test runs.

    `FymoApp.__init__` (fymo/core/server.py) inserts `project_root` onto
    `sys.path` so `app.*` is importable, but never removes it or clears
    `sys.modules` afterward. Since every blog_app copy uses the same
    top-level package name ("app"), a second test in the same pytest
    process that uses this fixture with a *different* tmp_path would
    otherwise silently reuse the first test's cached `app.data.db` (etc.)
    module -- e.g. `seed_test_post()` would insert its row into the FIRST
    test's SQLite file, not the current test's, and the current test's own
    server would then see an empty database with no error at all, just a
    confusing 404. Clean up both `sys.path` and the cached `app.*` modules
    after each test using this fixture, matching the pattern already used
    by the local `blog_app` overrides in test_soft_nav.py and
    test_layout_system_e2e.py.
    """
    import sys
    dest = tmp_path / "blog_app"
    shutil.copytree(
        BLOG_APP, dest,
        ignore=shutil.ignore_patterns("node_modules", "dist", ".fymo", "app/data", "__pycache__"),
    )
    nm = BLOG_APP / "node_modules"
    if nm.is_dir():
        (dest / "node_modules").symlink_to(nm)
    else:
        pytest.skip("examples/blog_app/node_modules not found — run npm install in examples/blog_app/")
    dest_str = str(dest)
    yield dest
    if dest_str in sys.path:
        sys.path.remove(dest_str)
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


@pytest.fixture(scope="session")
def node_available() -> None:
    """Skip the test if `node` is not on PATH."""
    try:
        subprocess.run(["node", "--version"], check=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("node not installed")
