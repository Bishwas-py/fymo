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
    assert data["version"] == 1
    assert data["routes"]["home"]["ssr"] == "ssr/home.mjs"


def test_read_missing_returns_none(tmp_path: Path):
    assert Manifest.read(tmp_path / "missing.json") is None


def test_read_rejects_unknown_version(tmp_path: Path):
    out = tmp_path / "manifest.json"
    out.write_text(json.dumps({"version": 99, "routes": {}}))
    import pytest
    with pytest.raises(ValueError, match="version"):
        Manifest.read(out)
