from pathlib import Path
from fymo.build.discovery import discover_routes, Route


def test_discover_finds_top_level_index_svelte(example_app: Path):
    routes = discover_routes(example_app / "app" / "templates")
    names = sorted(r.name for r in routes)
    assert names == ["home", "todos"]


def test_route_entry_path_is_absolute(example_app: Path):
    routes = discover_routes(example_app / "app" / "templates")
    for r in routes:
        assert r.entry_path.is_absolute()
        assert r.entry_path.name == "index.svelte"


def test_discover_ignores_non_index(tmp_path: Path):
    templates = tmp_path / "templates"
    (templates / "todos").mkdir(parents=True)
    (templates / "todos" / "index.svelte").write_text("<div></div>")
    (templates / "todos" / "test.svelte").write_text("<div></div>")  # not an entry
    routes = discover_routes(templates)
    assert [r.name for r in routes] == ["todos"]
