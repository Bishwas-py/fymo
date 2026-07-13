"""Security + behavior tests for AssetManager static file serving."""

from pathlib import Path

import pytest

from fymo.core.assets import AssetManager


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A minimal project tree with one legitimate static asset and a secret
    file living OUTSIDE app/static (a stand-in for /etc/passwd, source, config)."""
    static = tmp_path / "app" / "static"
    static.mkdir(parents=True)
    (static / "logo.txt").write_text("i am a public asset")
    (tmp_path / "secret.txt").write_text("TOP SECRET credentials")
    return tmp_path


def test_serves_legitimate_static_file(project: Path):
    mgr = AssetManager(project)
    content, status, _ = mgr.serve_asset("/assets/logo.txt")
    assert status == "200 OK"
    assert content == "i am a public asset"


def test_dotdot_traversal_cannot_escape_static_dir(project: Path):
    """`/assets/../../secret.txt` climbs from app/static back to the project
    root and must not read files outside app/static."""
    mgr = AssetManager(project)
    content, status, _ = mgr.serve_asset("/assets/../../secret.txt")
    assert not status.startswith("200"), f"traversal leaked file: {content!r}"
    assert "TOP SECRET" not in content


def test_absolute_path_injection_cannot_escape_static_dir(project: Path):
    """`/assets//abs/path` — pathlib's `/` resets to the absolute operand, so a
    naive join reads an arbitrary absolute file. Must be blocked."""
    mgr = AssetManager(project)
    secret = project / "secret.txt"
    # serve_asset strips the '/assets/' prefix, leaving an absolute '/....'
    content, status, _ = mgr.serve_asset(f"/assets/{secret}")
    assert not status.startswith("200"), f"absolute-path read leaked file: {content!r}"
    assert "TOP SECRET" not in content
