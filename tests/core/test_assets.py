"""Security + behavior tests for AssetManager static file serving."""

from pathlib import Path

import pytest

from fymo.core.assets import AssetManager


# Real binary fixtures: actual file-format magic followed by bytes that are
# not valid UTF-8, so any decode() sneaking back into the serving path
# fails these tests immediately (issue #74).
WOFF2_BYTES = b"wOF2\x00\x01\x00\x00" + bytes(range(256))
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89"
)


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
    content, status, _, _ = mgr.serve_asset("/assets/logo.txt")
    assert status == "200 OK"
    assert content == b"i am a public asset"


def test_dotdot_traversal_cannot_escape_static_dir(project: Path):
    """`/assets/../../secret.txt` climbs from app/static back to the project
    root and must not read files outside app/static."""
    mgr = AssetManager(project)
    content, status, _, _ = mgr.serve_asset("/assets/../../secret.txt")
    assert not status.startswith("200"), f"traversal leaked file: {content!r}"
    assert b"TOP SECRET" not in content


def test_absolute_path_injection_cannot_escape_static_dir(project: Path):
    """`/assets//abs/path` — pathlib's `/` resets to the absolute operand, so a
    naive join reads an arbitrary absolute file. Must be blocked."""
    mgr = AssetManager(project)
    secret = project / "secret.txt"
    # serve_asset strips the '/assets/' prefix, leaving an absolute '/....'
    content, status, _, _ = mgr.serve_asset(f"/assets/{secret}")
    assert not status.startswith("200"), f"absolute-path read leaked file: {content!r}"
    assert b"TOP SECRET" not in content


def test_serves_woff2_byte_identical(project: Path):
    """Issue #74: a real woff2 (binary, not valid UTF-8) must come back 200
    with the exact bytes, not a 500 from content.decode('utf-8')."""
    fonts = project / "app" / "static" / "fonts"
    fonts.mkdir()
    (fonts / "Inter.woff2").write_bytes(WOFF2_BYTES)
    mgr = AssetManager(project)
    content, status, content_type, _ = mgr.serve_asset("/assets/fonts/Inter.woff2")
    assert status == "200 OK"
    assert content_type == "font/woff2"
    assert content == WOFF2_BYTES


def test_serves_png_byte_identical(project: Path):
    static = project / "app" / "static"
    (static / "logo.png").write_bytes(PNG_BYTES)
    mgr = AssetManager(project)
    content, status, content_type, _ = mgr.serve_asset("/assets/logo.png")
    assert status == "200 OK"
    assert content_type == "image/png"
    assert content == PNG_BYTES


def test_static_response_carries_etag_and_cache_control(project: Path):
    mgr = AssetManager(project)
    _, status, _, headers = mgr.serve_asset("/assets/logo.txt")
    assert status == "200 OK"
    assert headers.get("ETag", "").startswith('"')
    assert headers.get("Cache-Control") == "public, max-age=3600"


def test_if_none_match_returns_304_with_empty_body(project: Path):
    mgr = AssetManager(project)
    _, _, _, headers = mgr.serve_asset("/assets/logo.txt")
    etag = headers["ETag"]
    environ = {"HTTP_IF_NONE_MATCH": etag}
    content, status, _, headers = mgr.serve_asset("/assets/logo.txt", environ)
    assert status == "304 NOT MODIFIED"
    assert content == b""
    # The validator is resent so caches can refresh their entry's lifetime.
    assert headers["ETag"] == etag


def test_stale_if_none_match_returns_full_body(project: Path):
    mgr = AssetManager(project)
    environ = {"HTTP_IF_NONE_MATCH": '"deadbeef-0"'}
    content, status, _, _ = mgr.serve_asset("/assets/logo.txt", environ)
    assert status == "200 OK"
    assert content == b"i am a public asset"


def test_missing_static_file_is_404(project: Path):
    mgr = AssetManager(project)
    _, status, _, _ = mgr.serve_asset("/assets/nope.png")
    assert status == "404 NOT FOUND"
