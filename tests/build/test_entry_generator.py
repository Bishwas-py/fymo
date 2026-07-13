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
    assert "from 'svelte'" in text
    assert "hydrate" in text
    # relative import path from .fymo/entries/ back to templates/todos/index.svelte
    assert "../../templates/todos/index.svelte" in text
    assert "hydrate(Component" in text
    assert "svelte-app" in text
    assert "svelte-props" in text


def test_entry_includes_soft_nav_router(tmp_path: Path):
    """Each route's entry stub now ships the soft-nav click interceptor + popstate handler."""
    route = Route(name="home", entry_path=tmp_path / "templates/home/index.svelte")
    out_dir = tmp_path / ".fymo" / "entries"
    write_client_entries([route], out_dir, project_root=tmp_path)
    text = (out_dir / "home.client.js").read_text()
    assert "softNav" in text
    assert "/_fymo/data" in text
    assert "popstate" in text
    assert "history.pushState" in text
    # Imports the Svelte 5 mount/unmount API for swapping leaves
    assert "mount" in text
    assert "unmount" in text


def test_entry_reads_disabled_resources_meta(tmp_path: Path):
    """Entry stub looks up the fymo-disabled-resources meta to skip intercept."""
    route = Route(name="home", entry_path=tmp_path / "templates/home/index.svelte")
    out_dir = tmp_path / ".fymo" / "entries"
    write_client_entries([route], out_dir, project_root=tmp_path)
    text = (out_dir / "home.client.js").read_text()
    assert 'meta[name="fymo-disabled-resources"]' in text
    assert "isDisabledResource" in text


def test_entry_error_branch_shares_the_runtime_error_handling(tmp_path: Path):
    """Regression: this file's inlined __rpc had its own copy of the error
    branch, which drifted from fymo/remote/codegen.py's version and only
    ever surfaced the server's short error *code* (e.g. "internal"),
    dropping the real `message` — a caller's `catch` never saw the actual
    failure reason. Now both import the same fymo.remote.codegen.
    REMOTE_ERROR_THROW_JS constant, so they can't drift again."""
    route = Route(name="home", entry_path=tmp_path / "templates/home/index.svelte")
    out_dir = tmp_path / ".fymo" / "entries"
    write_client_entries([route], out_dir, project_root=tmp_path)
    text = (out_dir / "home.client.js").read_text()
    assert "env.message || env.error" in text
    assert "e.traceback = env.traceback;" in text


def test_no_layout_chain_generates_same_template_as_before(tmp_path: Path):
    from fymo.build.discovery import Route
    from fymo.build.entry_generator import write_client_entries
    leaf = tmp_path / "templates" / "home" / "index.svelte"
    leaf.parent.mkdir(parents=True)
    leaf.write_text("<div></div>")
    route = Route(name="home", entry_path=leaf)
    out_dir = tmp_path / "out"
    written = write_client_entries([route], out_dir, tmp_path)
    content = written["home"].read_text()
    assert "hydrate(Component" in content
    assert not (out_dir / "home.shell.svelte").exists()


def test_layout_chain_generates_shell_and_bootstrap(tmp_path: Path):
    from fymo.build.discovery import Route, LayoutRef
    from fymo.build.entry_generator import write_client_entries

    root_layout = tmp_path / "templates" / "_layout.svelte"
    root_layout.parent.mkdir(parents=True)
    root_layout.write_text("<div></div>")
    resource_layout = tmp_path / "templates" / "posts" / "_layout.svelte"
    resource_layout.parent.mkdir(parents=True)
    resource_layout.write_text("<div></div>")
    leaf = tmp_path / "templates" / "posts" / "show.svelte"
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
    written = write_client_entries([route], out_dir, tmp_path)

    shell_path = out_dir / "posts.shell.svelte"
    assert shell_path.exists()
    shell = shell_path.read_text()
    assert "import RootLayout from" in shell
    assert "import ResourceLayout from" in shell
    assert "import Leaf from" in shell
    assert "$state" in shell
    assert "export function swapLeaf" in shell
    assert "export function swapResourceLayout" in shell
    assert "export function updateRootLayoutProps" in shell
    assert "export function updateResourceLayoutProps" in shell
    assert "<svelte:boundary" in shell
    # Regression guard: the leaf must render in BOTH the {#if CurrentResourceLayout}
    # branch and the {:else} branch. <svelte:boundary> is now defined once inside
    # the shared {#snippet leafSlot()}, so a bare substring check on it can't tell
    # the two branches apart -- assert on {@render leafSlot()} appearing exactly
    # twice (once per branch) so a future edit that drops the {:else} render can't
    # regress silently.
    assert shell.count("{@render leafSlot()}") == 2

    bootstrap = written["posts"].read_text()
    assert "import Shell from './posts.shell.svelte'" in bootstrap
    assert "hydrate(Shell" in bootstrap
    assert "shellInstance.swapLeaf" in bootstrap
    assert "shellInstance.swapResourceLayout" in bootstrap
    assert "shellInstance.updateRootLayoutProps" in bootstrap
    assert "shellInstance.updateResourceLayoutProps" in bootstrap
    assert "unmount(currentMount)" not in bootstrap  # old full-remount path is gone for shell routes


def test_root_only_layout_chain_still_renders_leaf_in_else_branch(tmp_path: Path):
    """Regression: a route whose layout_chain has ONLY a root layout (no
    resource layout) still hits the shared {#snippet leafSlot()} inside the
    {:else} branch of the {#if CurrentResourceLayout} block. Proves the
    leaf-rendering path exists even when there's no resource layout at all,
    since this shape is exactly what triggered the original {:else} bug."""
    from fymo.build.discovery import Route, LayoutRef
    from fymo.build.entry_generator import write_client_entries

    root_layout = tmp_path / "templates" / "_layout.svelte"
    root_layout.parent.mkdir(parents=True)
    root_layout.write_text("<div></div>")
    leaf = tmp_path / "templates" / "about" / "index.svelte"
    leaf.parent.mkdir(parents=True)
    leaf.write_text("<div></div>")

    route = Route(
        name="about",
        entry_path=leaf,
        layout_chain=[
            LayoutRef(level="root", id="_root", svelte_path=root_layout, controller_module=None),
        ],
    )
    out_dir = tmp_path / "out"
    write_client_entries([route], out_dir, tmp_path)

    shell = (out_dir / "about.shell.svelte").read_text()
    assert "{@render leafSlot()}" in shell
    assert shell.count("{@render leafSlot()}") == 2
