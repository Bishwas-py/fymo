import json
import time
from pathlib import Path
from fymo.build.manifest import Manifest, RouteAssets
from fymo.core.manifest_cache import ManifestCache, ManifestUnavailable
import pytest


def test_loads_manifest_on_first_access(tmp_path: Path):
    Manifest(routes={"todos": RouteAssets(ssr="ssr/todos.mjs", client="client/todos.AB.js", css=None, preload=[])}).write(tmp_path / "manifest.json")
    cache = ManifestCache(tmp_path)
    assert cache.get().routes["todos"].ssr == "ssr/todos.mjs"


def test_reloads_when_file_mtime_changes(tmp_path: Path):
    p = tmp_path / "manifest.json"
    Manifest(routes={"todos": RouteAssets(ssr="ssr/todos.mjs", client="client/todos.A.js", css=None, preload=[])}).write(p)
    cache = ManifestCache(tmp_path)
    cache.get()  # prime

    time.sleep(0.01)  # mtime resolution
    Manifest(routes={"todos": RouteAssets(ssr="ssr/todos.mjs", client="client/todos.B.js", css=None, preload=[])}).write(p)

    assert cache.get().routes["todos"].client == "client/todos.B.js"


def test_raises_if_manifest_missing(tmp_path: Path):
    cache = ManifestCache(tmp_path)
    with pytest.raises(ManifestUnavailable):
        cache.get()
