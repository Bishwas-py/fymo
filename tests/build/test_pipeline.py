import json
from pathlib import Path
import pytest
from fymo.build.pipeline import BuildPipeline, BuildError


@pytest.mark.usefixtures("node_available")
def test_build_produces_dist_for_example_app(example_app: Path):
    pipeline = BuildPipeline(project_root=example_app)
    result = pipeline.build(dev=False)

    assert result.ok
    assert (example_app / "dist" / "manifest.json").is_file()
    assert (example_app / "dist" / "ssr" / "todos.mjs").is_file()
    assert (example_app / "dist" / "sidecar.mjs").is_file()

    # at least one hashed client bundle
    client_files = list((example_app / "dist" / "client").glob("todos.*.js"))
    assert len(client_files) == 1


@pytest.mark.usefixtures("node_available")
def test_manifest_lists_each_route(example_app: Path):
    BuildPipeline(project_root=example_app).build(dev=False)
    manifest = json.loads((example_app / "dist" / "manifest.json").read_text())
    assert "todos" in manifest["routes"]
    todos = manifest["routes"]["todos"]
    assert todos["ssr"] == "ssr/todos.mjs"
    assert todos["client"].startswith("client/todos.")
    assert todos["client"].endswith(".js")


def test_build_fails_loudly_on_missing_node(example_app: Path, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(BuildError, match="node"):
        BuildPipeline(project_root=example_app).build(dev=False)


@pytest.mark.usefixtures("node_available")
def test_build_output_css_is_external_not_injected(example_app: Path):
    """Regression guard: if css defaults ever drift (Svelte/esbuild-svelte
    upstream change), a route's CSS must still land in a separate .css file,
    not get injected into the JS bundle at runtime."""
    from fymo.build.pipeline import BuildPipeline
    result = BuildPipeline(example_app).build(dev=False)
    from fymo.build.manifest import Manifest
    manifest = Manifest.read(result.manifest_path)
    home_css = manifest.routes["home"].css
    assert home_css is not None
    css_path = example_app / "dist" / home_css
    assert css_path.is_file()
    js_path = example_app / "dist" / manifest.routes["home"].client
    js_content = js_path.read_text()
    # Injected CSS would show up as a style-injection call in the JS bundle.
    assert "append_styles" not in js_content


def test_pipeline_populates_layout_chain_and_layouts_manifest(blog_app: Path, node_available):
    """blog_app doesn't have a _layout.svelte yet at this point in the plan
    (Task 11 adds it) -- this test creates a minimal one inline so Task 7 is
    independently verifiable before the example app migration happens."""
    templates = blog_app / "app" / "templates"
    (templates / "_layout.svelte").write_text(
        "<script>\n  let { children } = $props();\n</script>\n{@render children()}\n"
    )
    from fymo.build.pipeline import BuildPipeline
    result = BuildPipeline(blog_app).build(dev=False)
    from fymo.build.manifest import Manifest
    manifest = Manifest.read(result.manifest_path)

    assert "_root" in manifest.layouts
    assert manifest.layouts["_root"].client.startswith("client/")

    for route_name in ("index", "posts", "tags"):
        chain = manifest.routes[route_name].layout_chain
        assert any(ref.level == "root" and ref.id == "_root" for ref in chain)
        assert manifest.routes[route_name].uses_layout_shell is True
        # SSR bundle for a layout route is the composed tree, not the bare leaf.
        assert manifest.routes[route_name].ssr == f"ssr/{route_name}.mjs"
        ssr_path = blog_app / "dist" / manifest.routes[route_name].ssr
        assert ssr_path.is_file()


def test_pipeline_layout_ids_with_dot_do_not_collide(blog_app: Path, node_available):
    """Regression test for a matching bug: `ref.id` is an unsanitized resource
    directory name, so two resource-level layouts with ids like "a" and
    "a.b" produce hashed output filenames "_layout-a.<hash>.js" and
    "_layout-a.b.<hash>.js" -- the latter also satisfies a naive
    `out_name.startswith(f"_layout-{ref.id}.")` check for id "a". Matching
    must instead be by path identity (metafile entryPoint vs
    ref.svelte_path), which does not have this collision."""
    templates = blog_app / "app" / "templates"
    for resource_id in ("a", "a.b"):
        resource_dir = templates / resource_id
        resource_dir.mkdir(parents=True, exist_ok=True)
        (resource_dir / "_layout.svelte").write_text(
            "<script>\n  let { children } = $props();\n</script>\n"
            f"<div data-layout-marker=\"marker-{resource_id.replace('.', '-')}\">"
            "{@render children()}</div>\n"
        )
    from fymo.build.pipeline import BuildPipeline
    result = BuildPipeline(blog_app).build(dev=False)
    from fymo.build.manifest import Manifest
    manifest = Manifest.read(result.manifest_path)

    assert "a" in manifest.layouts
    assert "a.b" in manifest.layouts
    assert manifest.layouts["a"].client != manifest.layouts["a.b"].client

    client_a = (blog_app / "dist" / manifest.layouts["a"].client).read_text()
    client_ab = (blog_app / "dist" / manifest.layouts["a.b"].client).read_text()
    assert "marker-a" in client_a
    assert "marker-a-b" not in client_a
    assert "marker-a-b" in client_ab


def test_pipeline_raises_on_unmatched_layout_output(blog_app: Path):
    """If esbuild's metafile has no output matching a discovered layout's
    svelte_path (e.g. due to a matching bug, or a build-tool quirk), the
    pipeline must fail loudly instead of silently dropping the layout from
    manifest.layouts -- mirrors the route branch's analogous BuildError."""
    templates = blog_app / "app" / "templates"
    (templates / "_layout.svelte").write_text(
        "<script>\n  let { children } = $props();\n</script>\n{@render children()}\n"
    )
    from fymo.build.pipeline import BuildPipeline
    from fymo.build.discovery import discover_routes, discover_all_layouts

    pipeline = BuildPipeline(blog_app)
    routes = discover_routes(templates)
    all_layouts = discover_all_layouts(templates)
    assert any(ref.id == "_root" for ref in all_layouts)

    # Fabricate an esbuild client metafile with output for every route (so
    # the route-side check passes) but none for any layout -- as if the
    # layout entry point's output never got emitted.
    fake_outputs = {
        f"dist/client/{r.name}.deadbeef.js": {"entryPoint": f"{r.name}.client.js"}
        for r in routes
    }
    fake_result = {"client": {"outputs": fake_outputs}}

    with pytest.raises(BuildError, match="esbuild produced no client output for layout '_root'"):
        pipeline._build_manifest(routes, fake_result, {}, all_layouts, False)


def test_pipeline_no_layout_routes_unaffected(example_app: Path, node_available):
    """todo_app has no _layout.svelte -- manifest routes must have empty
    layout_chain and uses_layout_shell=False, matching pre-feature behavior."""
    from fymo.build.pipeline import BuildPipeline
    result = BuildPipeline(example_app).build(dev=False)
    from fymo.build.manifest import Manifest
    manifest = Manifest.read(result.manifest_path)
    for route_name, assets in manifest.routes.items():
        assert assets.layout_chain == []
        assert assets.uses_layout_shell is False
    assert manifest.layouts == {}


def test_pipeline_global_css_produces_manifest_entry(example_app: Path, node_available):
    (example_app / "app" / "templates" / "_global.css").write_text("body { margin: 0; }")
    from fymo.build.pipeline import BuildPipeline
    result = BuildPipeline(example_app).build(dev=False)
    from fymo.build.manifest import Manifest
    manifest = Manifest.read(result.manifest_path)
    assert manifest.global_css is not None
    css_path = example_app / "dist" / manifest.global_css
    assert css_path.is_file()
    assert "margin" in css_path.read_text()


def test_pipeline_no_global_css_leaves_manifest_field_none(example_app: Path, node_available):
    from fymo.build.pipeline import BuildPipeline
    result = BuildPipeline(example_app).build(dev=False)
    from fymo.build.manifest import Manifest
    manifest = Manifest.read(result.manifest_path)
    assert manifest.global_css is None


def test_lib_and_components_aliases_resolve_to_real_files(blog_app: Path, node_available):
    """blog_app's real source imports via `$lib/auth` (Nav.svelte) and
    `$components/Nav.svelte` (_layout.svelte). Proves both aliases are
    load-bearing -- not just "the build happens not to error" -- via a
    negative control: the build must succeed with the real files present,
    then FAIL specifically once each aliased target is removed, showing
    the resolution genuinely depends on that exact file rather than
    silently falling back to something else. (Fingerprinting compiled
    output for identifier names doesn't work here since prod builds
    minify and rename local bindings; this is the reliable alternative.)
    """
    from fymo.build.pipeline import BuildPipeline

    # Positive: real files present, both aliases resolve, build succeeds.
    result = BuildPipeline(blog_app).build(dev=False)
    assert result.ok

    # Negative control for $lib/*: remove its target, confirm the build now
    # fails because Nav.svelte's `$lib/auth` import can no longer resolve.
    auth_ts = blog_app / "app" / "lib" / "auth.ts"
    auth_ts.rename(blog_app / "app" / "lib" / "auth.ts.bak")
    try:
        with pytest.raises(BuildError):
            BuildPipeline(blog_app).build(dev=False)
    finally:
        (blog_app / "app" / "lib" / "auth.ts.bak").rename(auth_ts)

    # Negative control for $components/*: remove its target, confirm the
    # build now fails because _layout.svelte's `$components/Nav.svelte`
    # import can no longer resolve.
    nav_svelte = blog_app / "app" / "components" / "Nav.svelte"
    nav_svelte.rename(blog_app / "app" / "components" / "Nav.svelte.bak")
    try:
        with pytest.raises(BuildError):
            BuildPipeline(blog_app).build(dev=False)
    finally:
        (blog_app / "app" / "components" / "Nav.svelte.bak").rename(nav_svelte)

    # Confirm the fixture is back to a fully working state (both renames
    # were restored) rather than just trusting the finally blocks ran.
    result = BuildPipeline(blog_app).build(dev=False)
    assert result.ok


def test_build_fails_on_svelte_file_in_controllers(example_app: Path, node_available):
    (example_app / "app" / "controllers" / "oops.svelte").write_text("<div></div>")
    with pytest.raises(BuildError, match="app/controllers/oops.svelte"):
        BuildPipeline(example_app).build(dev=False)


def test_build_fails_on_py_file_in_templates(example_app: Path, node_available):
    (example_app / "app" / "templates" / "oops.py").write_text("x = 1\n")
    with pytest.raises(BuildError, match="app/templates/oops.py"):
        BuildPipeline(example_app).build(dev=False)


def test_build_warns_but_succeeds_on_py_file_in_lib(example_app: Path, node_available, capsys):
    """Locked decision: app/lib/ is a warning, not a build failure, unlike
    the hard-error checks above."""
    (example_app / "app" / "lib").mkdir(parents=True, exist_ok=True)
    (example_app / "app" / "lib" / "oops.py").write_text("x = 1\n")

    result = BuildPipeline(example_app).build(dev=False)

    assert result.ok
    out = capsys.readouterr().out
    assert "app/lib/oops.py" in out
    assert "app/support" in out


def test_hygiene_check_runs_even_without_node_on_path(example_app: Path, monkeypatch):
    """The violation must be reported even when node isn't available at all
    -- proves this is a fast, up-front filesystem check that doesn't depend
    on (or get masked by) the node-availability check, not something that
    only surfaces once a real build gets underway."""
    (example_app / "app" / "controllers" / "oops.svelte").write_text("<div></div>")
    monkeypatch.setattr("fymo.build.prepare.shutil.which", lambda cmd: None)
    with pytest.raises(BuildError, match="app/controllers/oops.svelte"):
        BuildPipeline(example_app).build(dev=False)
