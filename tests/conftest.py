"""Shared pytest fixtures for fymo tests."""
import shutil
import subprocess
from pathlib import Path
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_APP = REPO_ROOT / "examples" / "todo_app"


@pytest.fixture
def example_app(tmp_path: Path) -> Path:
    """Copy of examples/todo_app into an isolated tmp dir."""
    dest = tmp_path / "todo_app"
    shutil.copytree(EXAMPLE_APP, dest, ignore=shutil.ignore_patterns("node_modules", "dist", ".fymo"))
    # symlink node_modules from the original to save time
    (dest / "node_modules").symlink_to(EXAMPLE_APP / "node_modules")
    return dest


@pytest.fixture(scope="session")
def node_available() -> bool:
    try:
        subprocess.run(["node", "--version"], check=True, capture_output=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("node not installed")
        return False
