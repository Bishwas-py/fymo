from pathlib import Path
from fymo.build.discovery import Route, LayoutRef
from fymo.build.composition_generator import generate_ssr_tree


def test_returns_none_when_no_layout_chain(tmp_path: Path):
    route = Route(name="home", entry_path=tmp_path / "home" / "index.svelte")
    assert generate_ssr_tree(route, tmp_path / "out") is None


def test_writes_tree_file_for_root_only_chain(tmp_path: Path):
    root_layout = tmp_path / "app" / "templates" / "_layout.svelte"
    root_layout.parent.mkdir(parents=True)
    root_layout.write_text("<div></div>")
    leaf = tmp_path / "app" / "templates" / "home" / "index.svelte"
    leaf.parent.mkdir(parents=True)
    leaf.write_text("<div></div>")

    route = Route(
        name="home",
        entry_path=leaf,
        layout_chain=[LayoutRef(level="root", id="_root", svelte_path=root_layout, controller_module=None)],
    )
    out_dir = tmp_path / "out"
    result = generate_ssr_tree(route, out_dir)
    assert result == out_dir / "home.tree.svelte"
    content = result.read_text()
    assert "import RootLayout from" in content
    assert "import Leaf from" in content
    assert "ResourceLayout" not in content
    assert "<RootLayout" in content
    assert "<Leaf" in content
    assert "layoutProps.root" in content
    assert "leafProps" in content


def test_writes_tree_file_for_root_and_resource_chain(tmp_path: Path):
    root_layout = tmp_path / "app" / "templates" / "_layout.svelte"
    root_layout.parent.mkdir(parents=True)
    root_layout.write_text("<div></div>")
    resource_layout = tmp_path / "app" / "templates" / "posts" / "_layout.svelte"
    resource_layout.parent.mkdir(parents=True)
    resource_layout.write_text("<div></div>")
    leaf = tmp_path / "app" / "templates" / "posts" / "show.svelte"
    leaf.write_text("<div></div>")

    route = Route(
        name="posts",
        entry_path=leaf,
        layout_chain=[
            LayoutRef(level="root", id="_root", svelte_path=root_layout, controller_module=None),
            LayoutRef(level="resource", id="posts", svelte_path=resource_layout, controller_module=None),
        ],
    )
    out_dir = tmp_path / "out"
    result = generate_ssr_tree(route, out_dir)
    content = result.read_text()
    assert "import RootLayout from" in content
    assert "import ResourceLayout from" in content
    assert "import Leaf from" in content
    assert "<RootLayout" in content
    assert "<ResourceLayout" in content
    assert "<Leaf" in content
    # Root must nest outside resource, resource outside leaf.
    assert content.index("<RootLayout") < content.index("<ResourceLayout") < content.index("<Leaf")


def test_missing_layout_file_raises_filenotfounderror(tmp_path: Path):
    """Discovery only sets a chain entry for files it found, but the file
    could be deleted between discovery and generation (e.g. a `fymo dev`
    race) -- generation must fail loudly, not silently skip the layout."""
    import pytest
    leaf = tmp_path / "app" / "templates" / "home" / "index.svelte"
    leaf.parent.mkdir(parents=True)
    leaf.write_text("<div></div>")
    missing_layout = tmp_path / "app" / "templates" / "_layout.svelte"  # never written to disk

    route = Route(
        name="home",
        entry_path=leaf,
        layout_chain=[LayoutRef(level="root", id="_root", svelte_path=missing_layout, controller_module=None)],
    )
    with pytest.raises(FileNotFoundError, match="_layout.svelte"):
        generate_ssr_tree(route, tmp_path / "out")


def test_missing_leaf_file_raises_filenotfounderror(tmp_path: Path):
    import pytest
    root_layout = tmp_path / "app" / "templates" / "_layout.svelte"
    root_layout.parent.mkdir(parents=True)
    root_layout.write_text("<div></div>")
    missing_leaf = tmp_path / "app" / "templates" / "home" / "index.svelte"  # never written

    route = Route(
        name="home",
        entry_path=missing_leaf,
        layout_chain=[LayoutRef(level="root", id="_root", svelte_path=root_layout, controller_module=None)],
    )
    with pytest.raises(FileNotFoundError, match="index.svelte"):
        generate_ssr_tree(route, tmp_path / "out")
