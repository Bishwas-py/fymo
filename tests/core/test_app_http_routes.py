"""Tests for the app-level HTTP routes seam (app/routes.py -> FymoApp._dispatch)."""
import io
import sys
from pathlib import Path

import pytest

from fymo.core.http import HttpRoute, discover_app_http_routes


def test_discover_returns_empty_list_when_routes_file_missing(tmp_path: Path):
    assert discover_app_http_routes(tmp_path) == []


def test_discover_returns_empty_list_when_no_http_routes_function(tmp_path: Path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "routes.py").write_text("X = 1\n")
    assert discover_app_http_routes(tmp_path) == []


def test_discover_loads_routes_from_app_routes_py(tmp_path: Path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "routes.py").write_text(
        "from fymo.core.http import HttpRoute\n"
        "\n"
        "def _handler(environ, start_response):\n"
        "    start_response('200 OK', [('Content-Type', 'text/plain')])\n"
        "    return [b'hello']\n"
        "\n"
        "def http_routes():\n"
        "    return [HttpRoute(method='GET', path='/media/hello/', handler=_handler)]\n"
    )
    routes = discover_app_http_routes(tmp_path)
    assert len(routes) == 1
    assert routes[0].method == "GET"
    assert routes[0].path == "/media/hello/"
    assert callable(routes[0].handler)


def test_discover_raises_on_non_list_return(tmp_path: Path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "routes.py").write_text("def http_routes():\n    return 'not a list'\n")
    with pytest.raises(TypeError, match="must return a list"):
        discover_app_http_routes(tmp_path)


def test_two_project_roots_dont_collide(tmp_path_factory):
    """Two different projects each defining app/routes.py must not shadow
    each other's module in sys.modules within the same process (matters for
    a test session, and for any host process that ever loads more than one
    fymo project)."""
    root_a = tmp_path_factory.mktemp("proj_a")
    (root_a / "app").mkdir()
    (root_a / "app" / "routes.py").write_text(
        "from fymo.core.http import HttpRoute\n"
        "def _h(e, s):\n    s('200 OK', [])\n    return [b'a']\n"
        "def http_routes():\n    return [HttpRoute(method='GET', path='/a/', handler=_h)]\n"
    )
    root_b = tmp_path_factory.mktemp("proj_b")
    (root_b / "app").mkdir()
    (root_b / "app" / "routes.py").write_text(
        "from fymo.core.http import HttpRoute\n"
        "def _h(e, s):\n    s('200 OK', [])\n    return [b'b']\n"
        "def http_routes():\n    return [HttpRoute(method='GET', path='/b/', handler=_h)]\n"
    )
    routes_a = discover_app_http_routes(root_a)
    routes_b = discover_app_http_routes(root_b)
    assert routes_a[0].path == "/a/"
    assert routes_b[0].path == "/b/"

    # The whole point of the hash-unique module name is that each project's
    # app/routes.py is actually registered in sys.modules under its own key
    # (not just returned correctly) — assert that guarantee directly rather
    # than only inferring it from the returned routes.
    mod_name_a = f"_fymo_app_routes_{abs(hash(str((root_a / 'app' / 'routes.py').resolve())))}"
    mod_name_b = f"_fymo_app_routes_{abs(hash(str((root_b / 'app' / 'routes.py').resolve())))}"
    assert mod_name_a != mod_name_b
    assert mod_name_a in sys.modules
    assert mod_name_b in sys.modules
    assert sys.modules[mod_name_a] is not sys.modules[mod_name_b]
    assert sys.modules[mod_name_a].http_routes()[0].path == "/a/"
    assert sys.modules[mod_name_b].http_routes()[0].path == "/b/"


def _make_wsgi_env(path: str, method: str = "GET") -> dict:
    return {
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


@pytest.mark.usefixtures("node_available")
def test_fymo_app_dispatches_app_route(example_app: Path, monkeypatch):
    monkeypatch.setenv("FYMO_SECRET", "test-secret-please-do-not-use-in-prod-32b!")
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)

    app_dir = example_app / "app"
    (app_dir / "routes.py").write_text(
        "from fymo.core.http import HttpRoute\n"
        "\n"
        "def _handler(environ, start_response):\n"
        "    start_response('200 OK', [('Content-Type', 'text/plain')])\n"
        "    return [b'app-route-ok']\n"
        "\n"
        "def http_routes():\n"
        "    return [HttpRoute(method='GET', path='/media/hello/', handler=_handler)]\n"
    )

    from fymo import create_app
    app = create_app(example_app)
    try:
        captured = {}

        def start_response(status, headers, exc_info=None):
            captured["status"] = status
            captured["headers"] = headers

        body = b"".join(app(_make_wsgi_env("/media/hello/world"), start_response))
        assert captured["status"] == "200 OK"
        assert body == b"app-route-ok"
    finally:
        app.shutdown()


@pytest.mark.usefixtures("node_available")
def test_fymo_app_boots_fine_with_no_app_routes_py(example_app: Path, monkeypatch):
    """An app with no app/routes.py at all must not crash on init or on a
    request to an unmatched path — it should fall through to the normal
    SSR/asset handling exactly as before this feature existed."""
    monkeypatch.setenv("FYMO_SECRET", "test-secret-please-do-not-use-in-prod-32b!")
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)

    from fymo import create_app
    app = create_app(example_app)
    try:
        assert app._app_routes == []
    finally:
        app.shutdown()


@pytest.mark.usefixtures("node_available")
def test_fymo_app_dispatches_declarative_media_route(example_app: Path, monkeypatch):
    """`media:` in fymo.yml must produce a working route through the same
    `_app_routes` seam app/routes.py uses, with no app/routes.py involved at
    all, config-only wiring end to end."""
    monkeypatch.setenv("FYMO_SECRET", "test-secret-please-do-not-use-in-prod-32b!")
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)

    video_dir = example_app / "data" / "videos"
    video_dir.mkdir(parents=True)
    (video_dir / "clip.webm").write_bytes(b"video-bytes")

    from fymo import create_app
    app = create_app(example_app, config={
        "media": [
            {"prefix": "/media/videos/", "dir": "data/videos", "extensions": ["webm"]},
        ],
        "storage": {"provider": "local"},
    })
    try:
        captured = {}

        def start_response(status, headers, exc_info=None):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(app(_make_wsgi_env("/media/videos/clip.webm"), start_response))
        assert captured["status"] == "200 OK"
        assert captured["headers"]["Content-Type"] == "video/webm"
        assert body == b"video-bytes"
    finally:
        app.shutdown()


@pytest.mark.usefixtures("node_available")
def test_fymo_app_rejects_media_traversal_through_full_dispatch(example_app: Path, monkeypatch):
    """Same traversal attack as tests/core/test_media.py's route-handler-level
    test, but driven through `app(environ, start_response)` (FymoApp.__call__)
    end to end, so it also exercises the body-cap/rate-limit/security-header
    chain and the prefix-matching loop in `_dispatch`, not just the media
    route's own handler in isolation."""
    monkeypatch.setenv("FYMO_SECRET", "test-secret-please-do-not-use-in-prod-32b!")
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)

    video_dir = example_app / "data" / "videos"
    video_dir.mkdir(parents=True)
    (example_app / "secret.webm").write_bytes(b"top secret")

    from fymo import create_app
    app = create_app(example_app, config={
        "media": [
            {"prefix": "/media/videos/", "dir": "data/videos", "extensions": ["webm"]},
        ],
        "storage": {"provider": "local"},
    })
    try:
        captured = {}

        def start_response(status, headers, exc_info=None):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(app(
            _make_wsgi_env("/media/videos/../../secret.webm"), start_response
        ))
        assert captured["status"] == "400 Bad Request"
        assert b"top secret" not in body
    finally:
        app.shutdown()


@pytest.mark.usefixtures("node_available")
def test_fymo_app_raises_when_media_configured_without_storage(example_app: Path, monkeypatch):
    """`fymo build`'s hygiene check (tests/build/test_storage_hygiene.py) catches
    this for the normal `fymo build` -> `fymo run` path, but `fymo dev` and a
    stale `dist/` built before `media:` was added can both reach FymoApp.__init__
    without ever running that check. Runtime has to refuse to silently assume
    local storage too, not just build time."""
    monkeypatch.setenv("FYMO_SECRET", "test-secret-please-do-not-use-in-prod-32b!")
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)

    from fymo import create_app
    with pytest.raises(Exception, match="storage"):
        create_app(example_app, config={
            "media": [
                {"prefix": "/media/videos/", "dir": "data/videos", "extensions": ["webm"]},
            ],
        })


@pytest.mark.usefixtures("node_available")
def test_fymo_app_registers_storage_provider_without_media_configured(example_app: Path, monkeypatch):
    """Issue #31: app code (a job) needs the configured StorageProvider even
    when the app never declares `media:` routes. storage: alone must be
    enough to make fymo.storage.get_storage_provider() usable."""
    monkeypatch.setenv("FYMO_SECRET", "test-secret-please-do-not-use-in-prod-32b!")
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)

    from fymo import create_app
    from fymo.storage import get_storage_provider, reset_storage_provider
    from fymo.storage.providers.local import LocalStorageProvider

    reset_storage_provider()
    app = create_app(example_app, config={"storage": {"provider": "local"}})
    try:
        assert isinstance(app.storage_provider, LocalStorageProvider)
        assert get_storage_provider() is app.storage_provider
    finally:
        app.shutdown()
        reset_storage_provider()


@pytest.mark.usefixtures("node_available")
def test_fymo_app_media_routes_reuse_the_process_wide_storage_provider(example_app: Path, monkeypatch):
    """The instance FymoApp hands to build_media_routes must be the exact
    same object fymo.storage.get_storage_provider() returns elsewhere in the
    process, not a second provider built separately, since a real provider
    (an S3 client, once #17 lands) shouldn't be constructed twice per app."""
    monkeypatch.setenv("FYMO_SECRET", "test-secret-please-do-not-use-in-prod-32b!")
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)

    video_dir = example_app / "data" / "videos"
    video_dir.mkdir(parents=True)
    (video_dir / "clip.webm").write_bytes(b"video-bytes")

    from fymo import create_app
    from fymo.storage import get_storage_provider, reset_storage_provider

    reset_storage_provider()
    app = create_app(example_app, config={
        "media": [
            {"prefix": "/media/videos/", "dir": "data/videos", "extensions": ["webm"]},
        ],
        "storage": {"provider": "local"},
    })
    try:
        assert get_storage_provider() is app.storage_provider
    finally:
        app.shutdown()
        reset_storage_provider()


@pytest.mark.usefixtures("node_available")
def test_fymo_app_leaves_storage_uninitialized_when_not_configured(example_app: Path, monkeypatch):
    """No storage: section at all (and no media: to require one) must not
    silently register a default provider — get_storage_provider() should
    still raise, matching build_storage_provider's no-default guarantee."""
    monkeypatch.setenv("FYMO_SECRET", "test-secret-please-do-not-use-in-prod-32b!")
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)

    from fymo import create_app
    from fymo.storage import get_storage_provider, reset_storage_provider

    reset_storage_provider()
    app = create_app(example_app)
    try:
        assert app.storage_provider is None
        with pytest.raises(RuntimeError, match="storage is not initialized"):
            get_storage_provider()
    finally:
        app.shutdown()
        reset_storage_provider()
