"""Tests for declarative media routes (fymo.yml `media:` section ->
fymo.core.media.build_media_routes -> HttpRoute list).

These exercise the built route's WSGI handler directly with a real WSGI
environ (mirroring tests/core/test_app_http_routes.py's `_make_wsgi_env`
helper) rather than unit-testing an internal validation function in
isolation. The point is to prove the actual dispatch path a request would
take is safe, not just that some helper returns the right boolean.
"""
import io
from pathlib import Path

import pytest

from fymo.core.media import build_media_routes


def _make_wsgi_env(path: str, method: str = "GET", range_header: str | None = None) -> dict:
    env = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "wsgi.input": io.BytesIO(b""),
        "wsgi.errors": io.StringIO(),
        "wsgi.version": (1, 0),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
        "wsgi.url_scheme": "http",
    }
    if range_header is not None:
        env["HTTP_RANGE"] = range_header
    return env


def _capture():
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(headers)

    return captured, start_response


def _one_route(tmp_path: Path, extensions=("webm",)):
    routes = build_media_routes(tmp_path, [
        {"prefix": "/media/videos/", "dir": "data/videos", "extensions": list(extensions)},
    ])
    assert len(routes) == 1
    return routes[0]


def test_absent_media_config_registers_zero_routes(tmp_path: Path):
    assert build_media_routes(tmp_path, []) == []


def test_full_file_get_returns_200_with_content_length_and_type(tmp_path: Path):
    video_dir = tmp_path / "data" / "videos"
    video_dir.mkdir(parents=True)
    payload = b"x" * 1000
    (video_dir / "clip.webm").write_bytes(payload)

    route = _one_route(tmp_path)
    captured, start_response = _capture()
    body = b"".join(route.handler(_make_wsgi_env("/media/videos/clip.webm"), start_response))

    assert captured["status"] == "200 OK"
    assert captured["headers"]["Content-Length"] == str(len(payload))
    assert captured["headers"]["Content-Type"] == "video/webm"
    assert body == payload


def test_range_request_returns_206_with_correct_content_range_and_body_length(tmp_path: Path):
    video_dir = tmp_path / "data" / "videos"
    video_dir.mkdir(parents=True)
    payload = bytes(range(256)) * 4  # 1024 bytes
    (video_dir / "clip.webm").write_bytes(payload)

    route = _one_route(tmp_path)
    captured, start_response = _capture()
    env = _make_wsgi_env("/media/videos/clip.webm", range_header="bytes=0-99")
    body = b"".join(route.handler(env, start_response))

    assert captured["status"] == "206 Partial Content"
    assert captured["headers"]["Content-Range"] == f"bytes 0-99/{len(payload)}"
    assert captured["headers"]["Content-Length"] == "100"
    assert len(body) == 100
    assert body == payload[0:100]


def test_nonexistent_file_returns_404(tmp_path: Path):
    (tmp_path / "data" / "videos").mkdir(parents=True)
    route = _one_route(tmp_path)
    captured, start_response = _capture()
    route.handler(_make_wsgi_env("/media/videos/missing.webm"), start_response)
    assert captured["status"] == "404 Not Found"


@pytest.mark.parametrize("filename", ["../../etc/passwd.webm", "/etc/passwd.webm"])
def test_traversal_attempt_returns_400_through_real_wsgi_dispatch(tmp_path: Path, filename: str):
    """A real WSGI request whose PATH_INFO carries a traversal attempt must
    be rejected by the actual route handler, not a standalone validator
    function, proving the dispatch path itself is safe."""
    (tmp_path / "data" / "videos").mkdir(parents=True)
    # Plant a file outside the media dir that a successful traversal would read.
    (tmp_path / "secret.webm").write_bytes(b"top secret")

    route = _one_route(tmp_path)
    captured, start_response = _capture()
    body = b"".join(route.handler(_make_wsgi_env("/media/videos/" + filename), start_response))

    assert captured["status"] == "400 Bad Request"
    assert b"top secret" not in body


def test_disallowed_extension_returns_400(tmp_path: Path):
    video_dir = tmp_path / "data" / "videos"
    video_dir.mkdir(parents=True)
    (video_dir / "clip.mp4").write_bytes(b"not allowed")

    route = _one_route(tmp_path, extensions=("webm",))
    captured, start_response = _capture()
    route.handler(_make_wsgi_env("/media/videos/clip.mp4"), start_response)
    assert captured["status"] == "400 Bad Request"
