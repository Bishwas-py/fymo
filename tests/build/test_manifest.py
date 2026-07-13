import json
from pathlib import Path
from fymo.build.manifest import Manifest, RouteAssets


def test_write_and_read_roundtrip(tmp_path: Path):
    m = Manifest(routes={
        "todos": RouteAssets(
            ssr="ssr/todos.mjs",
            client="client/todos.A1B2.js",
            css="client/todos.A1B2.css",
            preload=["client/chunk-datefns.X9Y8.js"],
        )
    })
    out = tmp_path / "manifest.json"
    m.write(out)

    loaded = Manifest.read(out)
    assert loaded == m
    assert loaded.routes["todos"].css == "client/todos.A1B2.css"


def test_atomic_write_via_rename(tmp_path: Path):
    out = tmp_path / "manifest.json"
    Manifest(routes={"home": RouteAssets(ssr="ssr/home.mjs", client="client/home.X.js", css=None, preload=[])}).write(out)
    assert out.exists()
    assert not (tmp_path / "manifest.json.tmp").exists()
    data = json.loads(out.read_text())
    assert data["version"] == 2
    assert data["routes"]["home"]["ssr"] == "ssr/home.mjs"


def test_read_missing_returns_none(tmp_path: Path):
    assert Manifest.read(tmp_path / "missing.json") is None


def test_read_rejects_unknown_version(tmp_path: Path):
    out = tmp_path / "manifest.json"
    out.write_text(json.dumps({"version": 99, "routes": {}}))
    import pytest
    with pytest.raises(ValueError, match="version"):
        Manifest.read(out)


def test_manifest_carries_remote_modules(tmp_path: Path):
    from fymo.build.manifest import Manifest, RouteAssets, RemoteModuleAssets
    m = Manifest(
        routes={"home": RouteAssets(ssr="ssr/home.mjs", client="client/home.A.js", css=None, preload=[])},
        remote_modules={"posts": RemoteModuleAssets(hash="abc123def456", fns=["hello", "goodbye"])},
    )
    out = tmp_path / "manifest.json"
    m.write(out)
    loaded = Manifest.read(out)
    assert loaded == m
    assert loaded.remote_modules["posts"].hash == "abc123def456"
    assert loaded.remote_modules["posts"].fns == ["hello", "goodbye"]


def test_manifest_remote_modules_optional(tmp_path: Path):
    """Apps without app/remote/ should still produce valid manifests (empty dict)."""
    from fymo.build.manifest import Manifest, RouteAssets
    m = Manifest(routes={"home": RouteAssets(ssr="ssr/home.mjs", client="client/home.A.js", css=None, preload=[])})
    out = tmp_path / "manifest.json"
    m.write(out)
    loaded = Manifest.read(out)
    assert loaded.remote_modules == {}


def test_route_assets_layout_chain_roundtrips(tmp_path: Path):
    from fymo.build.manifest import Manifest, RouteAssets, LayoutRefAsset
    m = Manifest(routes={
        "posts": RouteAssets(
            ssr="ssr/posts.tree.mjs",
            client="client/posts.A1.js",
            css="client/posts.A1.css",
            preload=[],
            layout_chain=[
                LayoutRefAsset(level="root", id="_root", controller_module="app.controllers._layout"),
                LayoutRefAsset(level="resource", id="posts", controller_module=None),
            ],
            uses_layout_shell=True,
        )
    })
    out = tmp_path / "manifest.json"
    m.write(out)
    loaded = Manifest.read(out)
    assert loaded == m
    assert loaded.routes["posts"].layout_chain[0].level == "root"
    assert loaded.routes["posts"].layout_chain[1].id == "posts"
    assert loaded.routes["posts"].uses_layout_shell is True


def test_route_assets_defaults_have_no_layout_chain(tmp_path: Path):
    from fymo.build.manifest import Manifest, RouteAssets
    m = Manifest(routes={"home": RouteAssets(ssr="ssr/home.mjs", client="client/home.X.js", css=None, preload=[])})
    out = tmp_path / "manifest.json"
    m.write(out)
    loaded = Manifest.read(out)
    assert loaded.routes["home"].layout_chain == []
    assert loaded.routes["home"].uses_layout_shell is False


def test_manifest_layouts_and_global_css_roundtrip(tmp_path: Path):
    from fymo.build.manifest import Manifest, RouteAssets, LayoutAssets
    m = Manifest(
        routes={"home": RouteAssets(ssr="ssr/home.mjs", client="client/home.A.js", css=None, preload=[])},
        layouts={"_root": LayoutAssets(client="client/_layout-_root.H1.js", css="client/_layout-_root.H1.css")},
        global_css="client/global.G1.css",
    )
    out = tmp_path / "manifest.json"
    m.write(out)
    loaded = Manifest.read(out)
    assert loaded == m
    assert loaded.layouts["_root"].client == "client/_layout-_root.H1.js"
    assert loaded.global_css == "client/global.G1.css"


def test_manifest_layouts_and_global_css_optional(tmp_path: Path):
    from fymo.build.manifest import Manifest, RouteAssets
    m = Manifest(routes={"home": RouteAssets(ssr="ssr/home.mjs", client="client/home.A.js", css=None, preload=[])})
    out = tmp_path / "manifest.json"
    m.write(out)
    loaded = Manifest.read(out)
    assert loaded.layouts == {}
    assert loaded.global_css is None
