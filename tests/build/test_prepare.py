"""Tests for the shared pre-esbuild build-configuration preparation used by
both `fymo build` (BuildPipeline) and `fymo dev` (DevOrchestrator)."""
from pathlib import Path

import pytest

from fymo.build.prepare import BuildConfig, BuildError, prepare_build_config, read_yaml_section


def test_hygiene_violation_raises_build_error(example_app: Path):
    (example_app / "app" / "controllers" / "oops.svelte").write_text("<div></div>")
    dist_dir = example_app / "dist"
    cache_dir = example_app / ".fymo" / "entries"
    with pytest.raises(BuildError, match="app/controllers/oops.svelte"):
        prepare_build_config(example_app, dist_dir, cache_dir, dev=False)


def test_hygiene_violation_raises_before_node_check(example_app: Path, monkeypatch):
    """Same ordering rationale as before this extraction: the pure
    filesystem hygiene check must not be masked by (or wait on) the
    node-availability check."""
    (example_app / "app" / "controllers" / "oops.svelte").write_text("<div></div>")
    monkeypatch.setattr("fymo.build.prepare.shutil.which", lambda cmd: None)
    dist_dir = example_app / "dist"
    cache_dir = example_app / ".fymo" / "entries"
    with pytest.raises(BuildError, match="app/controllers/oops.svelte"):
        prepare_build_config(example_app, dist_dir, cache_dir, dev=False)


@pytest.mark.usefixtures("node_available")
def test_py_file_in_app_lib_warns_but_does_not_fail_build(example_app: Path, capsys):
    """Locked decision: unlike app/controllers, app/templates, and
    app/components, a .py file in app/lib/ is a warning, not a build
    failure. It must not raise, and prepare_build_config must still return
    a usable BuildConfig."""
    (example_app / "app" / "lib").mkdir(parents=True, exist_ok=True)
    (example_app / "app" / "lib" / "oops.py").write_text("x = 1\n")
    dist_dir = example_app / "dist"
    cache_dir = example_app / ".fymo" / "entries"

    config = prepare_build_config(example_app, dist_dir, cache_dir, dev=False)

    assert isinstance(config, BuildConfig)
    out = capsys.readouterr().out
    assert "app/lib/oops.py" in out
    assert "app/support" in out


@pytest.mark.usefixtures("node_available")
def test_no_app_lib_py_file_produces_no_warning(example_app: Path, capsys):
    dist_dir = example_app / "dist"
    cache_dir = example_app / ".fymo" / "entries"

    prepare_build_config(example_app, dist_dir, cache_dir, dev=False)

    out = capsys.readouterr().out
    assert "app/lib" not in out


def test_read_yaml_section_missing_file_returns_empty_dict(tmp_path: Path):
    assert read_yaml_section(tmp_path, "auth") == {}


def test_read_yaml_section_bad_yaml_returns_empty_dict(tmp_path: Path):
    (tmp_path / "fymo.yml").write_text(":\n  - not: valid: yaml")
    assert read_yaml_section(tmp_path, "auth") == {}


def test_read_yaml_section_returns_requested_key(tmp_path: Path):
    (tmp_path / "fymo.yml").write_text("auth:\n  enabled: true\nremote:\n  explicit_optin: true\n")
    assert read_yaml_section(tmp_path, "auth") == {"enabled": True}
    assert read_yaml_section(tmp_path, "remote") == {"explicit_optin": True}
    assert read_yaml_section(tmp_path, "missing") == {}


@pytest.mark.usefixtures("node_available")
def test_prepare_build_config_reflects_blog_app_facts(blog_app: Path):
    """blog_app has index/, posts/ (with a resource _layout.svelte and
    show.svelte), and tags/ (show.svelte, no resource layout), plus a root
    _layout.svelte -- so this pins the known shape of what prepare must
    produce for both `fymo build` and `fymo dev` to agree on."""
    dist_dir = blog_app / "dist"
    cache_dir = blog_app / ".fymo" / "entries"

    config = prepare_build_config(blog_app, dist_dir, cache_dir, dev=False)

    assert isinstance(config, BuildConfig)

    route_names = {r.name for r in config.routes}
    assert route_names == {"index", "posts", "tags"}

    layout_ids = {ref.id for ref in config.all_layouts}
    assert "_root" in layout_ids
    assert "posts" in layout_ids

    assert "_layout-_root" in config.client_entries
    assert "_layout-posts" in config.client_entries

    global_css_path = blog_app / "app" / "templates" / "_global.css"
    assert config.has_global_css == global_css_path.is_file()

    # Every route with a layout chain gets a composed `.tree.svelte` SSR
    # entry point living in cache_dir; routes without one fall back to the
    # raw leaf (unchanged behavior).
    ssr_by_name = {e["name"]: e["entryPath"] for e in config.ssr_entries}
    assert set(ssr_by_name) == route_names
    for r in config.routes:
        if r.layout_chain:
            assert ssr_by_name[r.name] == str(cache_dir / f"{r.name}.tree.svelte")
            assert Path(ssr_by_name[r.name]).is_file()
        else:
            assert ssr_by_name[r.name] == str(r.entry_path)
