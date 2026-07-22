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
    """The regenerated blog_app ships the scaffold's real root
    _layout.svelte, so the manifest must carry the chain for every
    route."""
    from fymo.build.pipeline import BuildPipeline
    result = BuildPipeline(blog_app).build(dev=False)
    from fymo.build.manifest import Manifest
    manifest = Manifest.read(result.manifest_path)

    assert "_root" in manifest.layouts
    assert manifest.layouts["_root"].client.startswith("client/")

    for route_name in ("home", "posts", "signin"):
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
        pipeline._build_manifest(routes, fake_result, {}, all_layouts)


def test_pipeline_no_layout_routes_unaffected(example_app: Path, node_available):
    """An app with no _layout.svelte gets empty layout_chain and
    uses_layout_shell=False, matching pre-layout behavior. The regenerated
    example ships a root layout, so the copy sheds it (and the app.css
    import that rides in it) to reach the layout-free state."""
    from fymo.build.pipeline import BuildPipeline
    (example_app / "app" / "templates" / "_layout.svelte").unlink()
    result = BuildPipeline(example_app).build(dev=False)
    from fymo.build.manifest import Manifest
    manifest = Manifest.read(result.manifest_path)
    for route_name, assets in manifest.routes.items():
        assert assets.layout_chain == []
        assert assets.uses_layout_shell is False
    assert manifest.layouts == {}


def test_pipeline_global_css_fails_with_migration_error(example_app: Path):
    """Issue #77: the _global.css magic filename is deleted, not deprecated.
    A project still shipping one fails the build with the exact fix."""
    (example_app / "app" / "templates" / "_global.css").write_text("body { margin: 0; }")
    with pytest.raises(BuildError) as exc:
        BuildPipeline(example_app).build(dev=False)
    assert str(exc.value) == (
        "Error: _global.css is no longer auto-injected. Move it to app/assets/app.css\n"
        "and add `import '../assets/app.css'` to app/templates/_layout.svelte."
    )


def test_pipeline_global_css_directory_fails_with_migration_error(example_app: Path):
    """Regression: a directory literally named app/templates/_global.css
    (a bad merge, a stray mkdir) must fail the same way a file does.
    is_file() returns False for a directory, so a naive check silently lets
    this through -- exactly the silent-missing-styles failure this issue
    exists to prevent, just reached through an edge case."""
    (example_app / "app" / "templates" / "_global.css").mkdir()
    with pytest.raises(BuildError) as exc:
        BuildPipeline(example_app).build(dev=False)
    assert str(exc.value) == (
        "Error: _global.css is no longer auto-injected. Move it to app/assets/app.css\n"
        "and add `import '../assets/app.css'` to app/templates/_layout.svelte."
    )


def test_pipeline_css_file_in_templates_fails_hygiene(example_app: Path):
    """Issue #77: stylesheets have one home. Any loose .css under
    app/templates/ is a hygiene build error naming the move."""
    (example_app / "app" / "templates" / "todos" / "extra.css").write_text("p { color: red; }")
    with pytest.raises(BuildError, match=r"stylesheets live in app/assets/, found app/templates/todos/extra\.css"):
        BuildPipeline(example_app).build(dev=False)


def _write_root_layout_importing_app_css(project: Path, css: str) -> None:
    assets_dir = project / "app" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "app.css").write_text(css)
    (project / "app" / "templates" / "_layout.svelte").write_text(
        "<script>\n  import '../assets/app.css';\n\n  let { children } = $props();\n</script>\n"
        "{@render children()}\n"
    )


def test_pipeline_layout_imported_css_lands_in_layout_manifest(example_app: Path, node_available):
    """Issue #77: a root layout importing app/assets/app.css gets that CSS
    bundled into its entry's sibling CSS output, tracked as LayoutAssets.css.
    The SSR pass must not choke on the .css import (empty-loaded)."""
    _write_root_layout_importing_app_css(example_app, "body { margin: 0; background: #abcdef; }")
    result = BuildPipeline(example_app).build(dev=False)
    from fymo.build.manifest import Manifest
    manifest = Manifest.read(result.manifest_path)
    assert manifest.layouts["_root"].css is not None
    css_path = example_app / "dist" / manifest.layouts["_root"].css
    assert css_path.is_file()
    assert "#abcdef" in css_path.read_text()


def test_pipeline_font_url_hashed_into_dist_and_rewritten(example_app: Path, node_available):
    """Issue #77 acceptance: a real @font-face with a real woff2 in
    app/assets/fonts/ builds; the font is content-hashed into dist/client/
    and the css url() is rewritten to a /dist/client/ path that serves."""
    woff2 = b"wOF2\x00\x01\x00\x00" + bytes(range(256))
    fonts_dir = example_app / "app" / "assets" / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    (fonts_dir / "inter.woff2").write_bytes(woff2)
    _write_root_layout_importing_app_css(
        example_app,
        "@font-face { font-family: 'Inter'; src: url('./fonts/inter.woff2') format('woff2'); }\n"
        "body { font-family: 'Inter', sans-serif; }\n",
    )
    result = BuildPipeline(example_app).build(dev=False)
    from fymo.build.manifest import Manifest
    manifest = Manifest.read(result.manifest_path)
    css_text = (example_app / "dist" / manifest.layouts["_root"].css).read_text()

    import re
    m = re.search(r"url\(\"?(/dist/client/inter\.[A-Z0-9]+\.woff2)\"?\)", css_text)
    assert m, f"font url not rewritten to /dist/client/: {css_text}"
    hashed_rel = m.group(1)[len("/dist/"):]
    hashed_file = example_app / "dist" / hashed_rel
    assert hashed_file.is_file()
    assert hashed_file.read_bytes() == woff2

    # The rewritten URL actually serves, byte-identical.
    from fymo.core.assets import AssetManager
    body, status, content_type, _ = AssetManager(example_app).serve_dist_asset(hashed_rel)
    assert status == "200 OK"
    assert content_type == "font/woff2"
    assert body == woff2


def test_pipeline_root_absolute_url_left_untouched(example_app: Path, node_available):
    """Root-absolute urls are verbatim static references (app/static/ at
    /static/), not build inputs: the bundle must leave them alone."""
    _write_root_layout_importing_app_css(
        example_app, "body { background-image: url('/static/bg.png'); }"
    )
    result = BuildPipeline(example_app).build(dev=False)
    from fymo.build.manifest import Manifest
    manifest = Manifest.read(result.manifest_path)
    css_text = (example_app / "dist" / manifest.layouts["_root"].css).read_text()
    assert "/static/bg.png" in css_text


def test_pipeline_bare_package_css_import_resolves_from_node_modules(example_app: Path, node_available):
    """`@import '@fontsource/inter';`-style bare specifiers resolve through
    the project's node_modules (nodePaths). The example fixture's
    node_modules is a read-only symlink, so rebuild it as a real directory
    of per-package symlinks plus one scratch fontsource-style package
    (package.json main pointing at a css file, the @fontsource convention)."""
    nm = example_app / "node_modules"
    real_nm = nm.resolve()
    nm.unlink()
    nm.mkdir()
    for pkg in real_nm.iterdir():
        if pkg.name.startswith("@"):
            scope = nm / pkg.name
            scope.mkdir()
            for sub in pkg.iterdir():
                (scope / sub.name).symlink_to(sub)
        else:
            (nm / pkg.name).symlink_to(pkg)
    scratch = nm / "@fontsource" / "scratch"
    scratch.mkdir(parents=True)
    (scratch / "package.json").write_text('{"name": "@fontsource/scratch", "main": "index.css"}\n')
    woff2 = b"wOF2\x00\x01\x00\x00" + bytes(range(256))
    (scratch / "files").mkdir()
    (scratch / "files" / "scratch.woff2").write_bytes(woff2)
    (scratch / "index.css").write_text(
        "@font-face { font-family: 'Scratch'; src: url('./files/scratch.woff2') format('woff2'); }\n"
    )

    _write_root_layout_importing_app_css(example_app, "@import '@fontsource/scratch';\n")
    result = BuildPipeline(example_app).build(dev=False)
    from fymo.build.manifest import Manifest
    manifest = Manifest.read(result.manifest_path)
    css_text = (example_app / "dist" / manifest.layouts["_root"].css).read_text()
    assert "Scratch" in css_text
    assert "/dist/client/scratch." in css_text


def test_lib_and_components_aliases_resolve_to_real_files(blog_app: Path, node_available):
    """Proves the $lib/* and $components/* aliases are load-bearing --
    not just "the build happens not to error" -- via a negative control:
    write real aliased files into the copy plus a template importing
    both, build green, then FAIL specifically once each aliased target
    is removed, showing the resolution genuinely depends on that exact
    file rather than silently falling back to something else. The
    regenerated blog no longer ships alias-using source of its own, so
    the test owns the files. (Fingerprinting compiled output for
    identifier names doesn't work here since prod builds minify and
    rename local bindings; this is the reliable alternative.)
    """
    from fymo.build.pipeline import BuildPipeline

    (blog_app / "app" / "lib" / "util.ts").write_text(
        "export const label: string = 'from-lib';\n"
    )
    (blog_app / "app" / "components" / "Badge.svelte").write_text(
        "<script>\n  import { label } from '$lib/util';\n</script>\n"
        "<span>{label}</span>\n"
    )
    probe = blog_app / "app" / "templates" / "aliasprobe"
    probe.mkdir()
    (probe / "index.svelte").write_text(
        "<script>\n  import Badge from '$components/Badge.svelte';\n</script>\n"
        "<Badge />\n"
    )

    # Positive: real files present, both aliases resolve, build succeeds.
    result = BuildPipeline(blog_app).build(dev=False)
    assert result.ok

    # Negative control for $lib/*: remove its target, confirm the build now
    # fails because Badge.svelte's `$lib/util` import can no longer resolve.
    util_ts = blog_app / "app" / "lib" / "util.ts"
    util_ts.rename(blog_app / "app" / "lib" / "util.ts.bak")
    try:
        with pytest.raises(BuildError):
            BuildPipeline(blog_app).build(dev=False)
    finally:
        (blog_app / "app" / "lib" / "util.ts.bak").rename(util_ts)

    # Negative control for $components/*: remove its target, confirm the
    # build now fails because the probe template's `$components/Badge.svelte`
    # import can no longer resolve.
    badge = blog_app / "app" / "components" / "Badge.svelte"
    badge.rename(blog_app / "app" / "components" / "Badge.svelte.bak")
    try:
        with pytest.raises(BuildError):
            BuildPipeline(blog_app).build(dev=False)
    finally:
        (blog_app / "app" / "components" / "Badge.svelte.bak").rename(badge)

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
