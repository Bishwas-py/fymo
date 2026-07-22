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


@pytest.fixture(autouse=True)
def _reset_remote_router_globals():
    """`FymoApp.__init__` (fymo/core/server.py) writes `_explicit_optin` and
    `_dev_mode` directly onto the `fymo.remote.router` module: real
    per-project config, not something a test fixture owns, so nothing
    restores it the way `monkeypatch.setattr` would. Any test that builds a
    FymoApp over a project with `remote.explicit_optin: true` (e.g. the
    blog_app fixture) leaves that global at True for every test that runs
    afterward in the same process, silently 404ing unmarked functions in
    unrelated tests that assume today's default. Reset after every test
    regardless of how it was set."""
    yield
    from fymo.remote import router as _remote_router
    _remote_router._explicit_optin = False
    _remote_router._dev_mode = False


@pytest.fixture
def example_app(tmp_path: Path) -> Path:
    """Copy of examples/todo_app into an isolated tmp dir.

    The example is pure generator output: the fymo new scaffold (root
    layout, home proof board, password auth with a signin page) plus
    `fymo generate resource todos` (controller, index/show/Item
    templates, app/remote/todos.py).

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

    Both examples are pure generator output with auth and remote
    functions; blog_app is the richer one (posts resource plus a
    comments remote), so tests exercising remote-module discovery use
    it. Same node_modules-symlink treatment as example_app: read-only,
    shared across test runs.

    `FymoApp.__init__` (fymo/core/server.py) inserts `project_root` onto
    `sys.path` so `app.*` is importable, but never removes it or clears
    `sys.modules` afterward. Since every blog_app copy uses the same
    top-level package name ("app"), a second test in the same pytest
    process that uses this fixture with a *different* tmp_path would
    otherwise silently reuse the first test's cached `app.*` modules,
    mutating the FIRST test's in-memory rows (or SQLite file) with no
    error at all, just confusing misses. This fixture inserts `dest`
    onto `sys.path` itself (some tests import `app.*` *before*
    constructing a FymoApp, so they can't rely on `FymoApp.__init__` to
    do it in time), and cleans up both `sys.path` and the cached `app.*`
    modules after each test using this fixture to prevent cross-test
    pollution when multiple tests use this fixture with different
    tmp_path instances.
    """
    import sys
    dest = tmp_path / "blog_app"
    shutil.copytree(
        BLOG_APP, dest,
        ignore=shutil.ignore_patterns("node_modules", "dist", ".fymo", "data", "__pycache__"),
    )
    nm = BLOG_APP / "node_modules"
    if nm.is_dir():
        (dest / "node_modules").symlink_to(nm)
    else:
        pytest.skip("examples/blog_app/node_modules not found — run npm install in examples/blog_app/")
    dest_str = str(dest)
    sys.path.insert(0, dest_str)
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
