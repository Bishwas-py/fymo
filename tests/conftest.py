"""Shared pytest fixtures for fymo tests."""
import shutil
import subprocess
from pathlib import Path
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_APP = REPO_ROOT / "examples" / "todo_app"


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


@pytest.fixture(scope="session")
def node_available() -> None:
    """Skip the test if `node` is not on PATH."""
    try:
        subprocess.run(["node", "--version"], check=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("node not installed")
