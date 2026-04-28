from pathlib import Path
from fymo.build.discovery import Route
from fymo.build.entry_generator import write_client_entries


def test_writes_one_entry_per_route(tmp_path: Path):
    route1 = Route(name="todos", entry_path=tmp_path / "templates/todos/index.svelte")
    route2 = Route(name="home", entry_path=tmp_path / "templates/home/index.svelte")
    out_dir = tmp_path / ".fymo" / "entries"

    paths = write_client_entries([route1, route2], out_dir, project_root=tmp_path)

    assert (out_dir / "todos.client.js").exists()
    assert (out_dir / "home.client.js").exists()
    assert paths["todos"] == out_dir / "todos.client.js"


def test_entry_imports_hydrate_and_component(tmp_path: Path):
    route = Route(name="todos", entry_path=tmp_path / "templates/todos/index.svelte")
    out_dir = tmp_path / ".fymo" / "entries"
    write_client_entries([route], out_dir, project_root=tmp_path)

    text = (out_dir / "todos.client.js").read_text()
    assert "import { hydrate } from 'svelte'" in text
    # relative import path from .fymo/entries/ back to templates/todos/index.svelte
    assert "../../templates/todos/index.svelte" in text
    assert "hydrate(Component" in text
    assert "svelte-app" in text
    assert "svelte-props" in text
