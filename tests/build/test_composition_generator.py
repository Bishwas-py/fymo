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
    assert "layoutProps.root" in content
    assert "leafProps" in content
    # Structural parity with the client shell (entry_generator.py's
    # SHELL_TEMPLATE): same leaf-slot snippet + boundary, same {#if}/{:else}/
    # {/if} wrapper shape, so SSR and client hydration anchors match.
    assert "{#snippet leafSlot()}" in content
    assert "<svelte:boundary" in content
    assert "{@render leafSlot()}" in content
    assert "{#if false}" in content
    assert "{:else}" in content
    assert "{/if}" in content
    # Regression guard: the leaf MUST be referenced via a $state-bound
    # "CurrentLeaf" tag, not the static "Leaf" import, directly as the
    # component tag. Svelte's compiler only emits the dynamic-component
    # codegen (a `$.component()` wrapper with its own hydration marker
    # comment) for tags bound to something other than a plain import/`let`
    # (kind != 'normal') -- the client shell's `CurrentLeaf` is `$state(...)`,
    # so it always compiles to that dynamic form. A static `<Leaf .../>` tag
    # here compiles WITHOUT that marker, so the server's HTML is missing the
    # comment the client's compiled `$.component()` call requires at
    # hydration time -- a real bug (`svelte.dev/e/hydration_mismatch`,
    # verified live in a browser) this test would otherwise miss entirely,
    # since it's invisible to a plain WSGI/curl check.
    assert "<CurrentLeaf" in content
    assert "let CurrentLeaf = $state(Leaf);" in content
    assert "<Leaf" not in content


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
    # Structural parity with the client shell: resource-layout slot is wrapped
    # in {#if}/{:else}/{/if} (literal `true` since this route has a resource
    # layout), and the leaf is rendered via the shared leafSlot snippet inside
    # a <svelte:boundary>, matching entry_generator.py's SHELL_TEMPLATE shape.
    assert "{#snippet leafSlot()}" in content
    assert "<svelte:boundary" in content
    assert "{#if true}" in content
    assert "{:else}" in content
    assert "{/if}" in content
    assert content.count("{@render leafSlot()}") == 2
    # Regression guard (see test_writes_tree_file_for_root_only_chain for the
    # full rationale): both the leaf AND the resource layout must be
    # referenced via $state-bound "Current*" tags, matching the client
    # shell's dynamic-component binding kind -- a static tag reference here
    # compiles without the hydration marker comment the client's compiled
    # `$.component()` call expects, causing a real hydration_mismatch.
    assert "<CurrentLeaf" in content
    assert "<CurrentResourceLayout" in content
    assert "let CurrentLeaf = $state(Leaf);" in content
    assert "let CurrentResourceLayout = $state(ResourceLayout);" in content
    assert "<Leaf" not in content
    assert "<ResourceLayout" not in content
    # Root must nest outside resource, resource outside the leaf-slot render,
    # in the composed tree section (i.e. after the leafSlot snippet
    # definition -- CurrentLeaf itself lives inside that snippet's own body,
    # which is defined once and referenced via {@render leafSlot()}, so
    # ordering is checked against the render call, not the snippet's internal
    # markup).
    tree_section = content.split("{/snippet}")[-1]
    assert (
        tree_section.index("<RootLayout")
        < tree_section.index("<CurrentResourceLayout")
        < tree_section.index("{@render leafSlot()}")
    )


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
