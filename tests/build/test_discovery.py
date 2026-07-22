from pathlib import Path
from fymo.build.discovery import discover_routes, Route


def test_discover_finds_top_level_index_svelte(example_app: Path):
    routes = discover_routes(example_app / "app" / "templates")
    names = sorted(r.name for r in routes)
    assert names == ["home", "signin", "todos"]


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


def test_route_has_no_layout_chain_when_none_exist(tmp_path: Path):
    # The regenerated example ships a root layout, so the no-layout case
    # needs its own tree.
    templates = tmp_path / "app" / "templates"
    (templates / "home").mkdir(parents=True)
    (templates / "home" / "index.svelte").write_text("<div></div>")
    routes = discover_routes(templates)
    assert [r.name for r in routes] == ["home"]
    for r in routes:
        assert r.layout_chain == []


def test_root_layout_applies_to_every_route(tmp_path: Path):
    from fymo.build.discovery import discover_routes, LayoutRef
    templates = tmp_path / "app" / "templates"
    (templates / "home").mkdir(parents=True)
    (templates / "home" / "index.svelte").write_text("<div></div>")
    (templates / "_layout.svelte").write_text("<div></div>")
    routes = discover_routes(templates)
    assert len(routes) == 1
    chain = routes[0].layout_chain
    assert len(chain) == 1
    assert chain[0].level == "root"
    assert chain[0].id == "_root"
    assert chain[0].svelte_path == (templates / "_layout.svelte").resolve()
    assert chain[0].controller_module is None  # no app/controllers/_layout.py written


def test_root_layout_controller_module_detected(tmp_path: Path):
    from fymo.build.discovery import discover_routes
    templates = tmp_path / "app" / "templates"
    (templates / "home").mkdir(parents=True)
    (templates / "home" / "index.svelte").write_text("<div></div>")
    (templates / "_layout.svelte").write_text("<div></div>")
    controllers = tmp_path / "app" / "controllers"
    controllers.mkdir(parents=True)
    (controllers / "_layout.py").write_text("def getContext():\n    return {}\n")
    routes = discover_routes(templates)
    assert routes[0].layout_chain[0].controller_module == "app.controllers._layout"


def test_resource_layout_only_applies_to_its_own_routes(tmp_path: Path):
    from fymo.build.discovery import discover_routes
    templates = tmp_path / "app" / "templates"
    (templates / "posts").mkdir(parents=True)
    (templates / "posts" / "show.svelte").write_text("<div></div>")
    (templates / "posts" / "_layout.svelte").write_text("<div></div>")
    (templates / "tags").mkdir(parents=True)
    (templates / "tags" / "show.svelte").write_text("<div></div>")
    routes = {r.name: r for r in discover_routes(templates)}
    assert len(routes["posts"].layout_chain) == 1
    assert routes["posts"].layout_chain[0].level == "resource"
    assert routes["posts"].layout_chain[0].id == "posts"
    assert routes["tags"].layout_chain == []


def test_root_before_resource_in_chain_order(tmp_path: Path):
    from fymo.build.discovery import discover_routes
    templates = tmp_path / "app" / "templates"
    (templates / "posts").mkdir(parents=True)
    (templates / "posts" / "show.svelte").write_text("<div></div>")
    (templates / "posts" / "_layout.svelte").write_text("<div></div>")
    (templates / "_layout.svelte").write_text("<div></div>")
    routes = discover_routes(templates)
    chain = routes[0].layout_chain
    assert [ref.level for ref in chain] == ["root", "resource"]


def test_discover_all_layouts_dedupes_across_routes(tmp_path: Path):
    from fymo.build.discovery import discover_all_layouts
    templates = tmp_path / "app" / "templates"
    (templates / "posts").mkdir(parents=True)
    (templates / "posts" / "show.svelte").write_text("<div></div>")
    (templates / "posts" / "index.svelte").write_text("<div></div>")
    (templates / "posts" / "_layout.svelte").write_text("<div></div>")
    (templates / "_layout.svelte").write_text("<div></div>")
    layouts = discover_all_layouts(templates)
    assert sorted(l.id for l in layouts) == ["_root", "posts"]
