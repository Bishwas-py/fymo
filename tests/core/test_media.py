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
def test_traversal_attempt_returns_400_via_route_handler(tmp_path: Path, filename: str):
    """The built route's handler (the actual WSGI callable a request would
    hit, not a standalone validator function) must reject a traversal
    attempt on its own. This calls `route.handler` directly rather than
    through FymoApp.__call__, so it does not exercise the prefix-matching /
    rate-limiter / security-header chain in front of it; see
    tests/core/test_app_http_routes.py for a full-FymoApp-dispatch version
    of this same attack."""
    (tmp_path / "data" / "videos").mkdir(parents=True)
    # Plant a file outside the media dir that a successful traversal would read.
    (tmp_path / "secret.webm").write_bytes(b"top secret")

    route = _one_route(tmp_path)
    captured, start_response = _capture()
    body = b"".join(route.handler(_make_wsgi_env("/media/videos/" + filename), start_response))

    assert captured["status"] == "400 Bad Request"
    assert b"top secret" not in body


def test_symlink_inside_media_dir_pointing_outside_is_rejected(tmp_path: Path):
    """A string-only traversal check (no '..', no leading '/') is not
    enough: a symlink physically planted inside the configured media dir
    can point anywhere, including outside root_dir, and its own filename
    contains neither '..' nor a leading '/'. The handler must resolve the
    final path and verify it is still contained within root_dir before
    serving it."""
    video_dir = tmp_path / "data" / "videos"
    video_dir.mkdir(parents=True)
    secret = tmp_path / "secret.webm"
    secret.write_bytes(b"top secret, outside the media dir")
    (video_dir / "evil.webm").symlink_to(secret)

    route = _one_route(tmp_path)
    captured, start_response = _capture()
    body = b"".join(route.handler(_make_wsgi_env("/media/videos/evil.webm"), start_response))

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


def test_malformed_range_header_returns_400_not_crash(tmp_path: Path):
    """Non-numeric Range values must be rejected cleanly, not raise a
    ValueError out of int() that crashes the request."""
    video_dir = tmp_path / "data" / "videos"
    video_dir.mkdir(parents=True)
    (video_dir / "clip.webm").write_bytes(b"x" * 1000)

    route = _one_route(tmp_path)
    captured, start_response = _capture()
    env = _make_wsgi_env("/media/videos/clip.webm", range_header="bytes=abc-def")
    route.handler(env, start_response)
    assert captured["status"] == "400 Bad Request"


def test_range_start_beyond_file_size_returns_416_not_crash(tmp_path: Path):
    """A start offset at or past the end of the file is an unsatisfiable
    range per RFC 7233, not a crash: `end - start + 1` going negative must
    never reach `f.read()`."""
    video_dir = tmp_path / "data" / "videos"
    video_dir.mkdir(parents=True)
    (video_dir / "clip.webm").write_bytes(b"x" * 1000)

    route = _one_route(tmp_path)
    captured, start_response = _capture()
    env = _make_wsgi_env("/media/videos/clip.webm", range_header="bytes=999999999-")
    route.handler(env, start_response)
    assert captured["status"] == "416 Range Not Satisfiable"
    assert captured["headers"]["Content-Range"] == "bytes */1000"


def test_range_end_before_start_returns_416_not_crash(tmp_path: Path):
    video_dir = tmp_path / "data" / "videos"
    video_dir.mkdir(parents=True)
    (video_dir / "clip.webm").write_bytes(b"x" * 1000)

    route = _one_route(tmp_path)
    captured, start_response = _capture()
    env = _make_wsgi_env("/media/videos/clip.webm", range_header="bytes=10-5")
    route.handler(env, start_response)
    assert captured["status"] == "416 Range Not Satisfiable"


def test_suffix_range_returns_the_actual_last_n_bytes(tmp_path: Path):
    """`bytes=-100` is RFC 7233's suffix-range syntax for "the last 100
    bytes", not "the first 100 bytes". partition("-") gives an empty
    start_str for this form, and that case must be handled explicitly."""
    video_dir = tmp_path / "data" / "videos"
    video_dir.mkdir(parents=True)
    payload = bytes(range(256)) * 4  # 1024 bytes
    (video_dir / "clip.webm").write_bytes(payload)

    route = _one_route(tmp_path)
    captured, start_response = _capture()
    env = _make_wsgi_env("/media/videos/clip.webm", range_header="bytes=-100")
    body = b"".join(route.handler(env, start_response))

    file_size = len(payload)
    assert captured["status"] == "206 Partial Content"
    assert captured["headers"]["Content-Range"] == f"bytes {file_size - 100}-{file_size - 1}/{file_size}"
    assert body == payload[-100:]


@pytest.mark.parametrize("entry", [
    {"dir": "data/videos", "extensions": ["webm"]},
    {"prefix": "/media/videos/", "extensions": ["webm"]},
])
def test_entry_missing_required_key_raises_value_error(tmp_path: Path, entry):
    """A raw KeyError at startup points at fymo's own code, not the bad
    fymo.yml entry. A descriptive ValueError names what's actually wrong."""
    with pytest.raises(ValueError, match="prefix.*dir|dir.*prefix"):
        build_media_routes(tmp_path, [entry])


@pytest.mark.parametrize("prefix", ["/dist/videos/", "/assets/videos/", "/dist/"])
def test_prefix_colliding_with_reserved_route_warns(tmp_path: Path, prefix, capsys):
    """`/dist/` and `/assets/` are matched by FymoApp._dispatch before the
    app-routes loop ever runs (fymo/core/server.py), so a media prefix
    under either would silently never be reached. Still registers the
    route (this is a warning, not a hard failure) but prints it loudly."""
    build_media_routes(tmp_path, [
        {"prefix": prefix, "dir": "data/videos", "extensions": ["webm"]},
    ])
    captured = capsys.readouterr()
    assert "Warning" in captured.out
    assert prefix in captured.out
