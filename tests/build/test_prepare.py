"""Tests for the shared pre-esbuild build-configuration preparation used by
both `fymo build` (BuildPipeline) and `fymo dev` (DevOrchestrator)."""
import sys
from pathlib import Path

import pytest

from fymo.build.prepare import BuildConfig, BuildError, prepare_build_config, read_yaml_section


@pytest.fixture(autouse=True)
def _cleanup_app_modules():
    """Tests below import app.remote.* modules (via prepare_build_config's
    remote discovery, which inserts/removes project_root on sys.path but
    never clears sys.modules). Without this, a cached `app.remote.versions`
    from one test's tmp_path leaks into a later test elsewhere in the suite
    that also uses the conventional `app.remote.posts` module name: same
    pollution risk documented on the `blog_app` fixture in conftest.py."""
    yield
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


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


def test_media_without_storage_raises_build_error(example_app: Path):
    (example_app / "fymo.yml").write_text(
        "media:\n"
        "  - prefix: /media/videos/\n"
        "    dir: data/videos\n"
        "    extensions: [webm]\n"
    )
    dist_dir = example_app / "dist"
    cache_dir = example_app / ".fymo" / "entries"
    with pytest.raises(BuildError, match="storage:"):
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


_REQUIRE_AUTH_MODULE = (
    "from fymo.auth import require_auth\n"
    "from fymo.remote import remote\n"
    "@remote\n"
    "@require_auth\n"
    "def create_comment(body: str) -> str: return body\n"
)


def test_require_auth_with_no_active_providers_raises_build_error(example_app: Path):
    """Issue #29: @require_auth shipped with auth off entirely must fail
    `fymo build`, naming the site, before node/esbuild runs. @remote here
    keeps the function clear of the unrelated #8 exposure check, isolating
    this test to the auth-enforcement failure."""
    (example_app / "app" / "remote").mkdir(parents=True, exist_ok=True)
    (example_app / "app" / "remote" / "__init__.py").write_text("")
    (example_app / "app" / "remote" / "comments.py").write_text(_REQUIRE_AUTH_MODULE)
    dist_dir = example_app / "dist"
    cache_dir = example_app / ".fymo" / "entries"
    with pytest.raises(BuildError, match="auth.enabled is not true"):
        prepare_build_config(example_app, dist_dir, cache_dir, dev=False)


def test_require_auth_with_no_active_providers_does_not_fail_dev(example_app: Path, monkeypatch):
    """Same misconfiguration, but `fymo dev`: an app is routinely mid-setup
    locally (auth not wired up yet), so this check is build-only, matching
    the "no routes" check's existing dev-mode exemption."""
    (example_app / "app" / "remote").mkdir(parents=True, exist_ok=True)
    (example_app / "app" / "remote" / "__init__.py").write_text("")
    (example_app / "app" / "remote" / "comments.py").write_text(_REQUIRE_AUTH_MODULE)
    monkeypatch.setattr("fymo.build.prepare.shutil.which", lambda cmd: "/usr/bin/node")
    dist_dir = example_app / "dist"
    cache_dir = example_app / ".fymo" / "entries"
    config = prepare_build_config(example_app, dist_dir, cache_dir, dev=True)
    assert isinstance(config, BuildConfig)


@pytest.mark.usefixtures("node_available")
def test_blog_app_require_auth_with_password_provider_builds_clean(blog_app: Path):
    """Regression check, not just a new-code assumption: blog_app already
    has auth.enabled true, the default password provider, and a real
    @require_auth site in app/remote/posts.py (create_comment). That's
    exactly the shape check_auth_enforcement_hygiene must let through."""
    dist_dir = blog_app / "dist"
    cache_dir = blog_app / ".fymo" / "entries"
    config = prepare_build_config(blog_app, dist_dir, cache_dir, dev=False)
    assert isinstance(config, BuildConfig)


def test_unmarked_remote_function_raises_build_error(example_app: Path):
    """Issue #8: with explicit_optin left at its default (false) and no
    allow_implicit escape hatch, an unmarked app/remote/*.py function must
    fail the build naming the specific function. Same ordering promise as
    directory hygiene: caught before node/esbuild."""
    (example_app / "app" / "remote").mkdir(parents=True, exist_ok=True)
    (example_app / "app" / "remote" / "__init__.py").write_text("")
    (example_app / "app" / "remote" / "versions.py").write_text(
        "def insert_version(x: str) -> str: return x\n"
    )
    dist_dir = example_app / "dist"
    cache_dir = example_app / ".fymo" / "entries"
    with pytest.raises(BuildError, match="insert_version"):
        prepare_build_config(example_app, dist_dir, cache_dir, dev=False)


def test_allow_implicit_escape_hatch_lets_unmarked_function_build(example_app: Path, monkeypatch):
    """remote.allow_implicit: true preserves today's behavior for apps not
    ready to migrate. The build must succeed, not just skip the hygiene
    error."""
    (example_app / "app" / "remote").mkdir(parents=True, exist_ok=True)
    (example_app / "app" / "remote" / "__init__.py").write_text("")
    (example_app / "app" / "remote" / "versions.py").write_text(
        "def insert_version(x: str) -> str: return x\n"
    )
    (example_app / "fymo.yml").write_text(
        (example_app / "fymo.yml").read_text() + "\nremote:\n  allow_implicit: true\n"
    )
    monkeypatch.setattr("fymo.build.prepare.shutil.which", lambda cmd: "/usr/bin/node")
    dist_dir = example_app / "dist"
    cache_dir = example_app / ".fymo" / "entries"
    config = prepare_build_config(example_app, dist_dir, cache_dir, dev=True)
    assert isinstance(config, BuildConfig)


def test_explicit_optin_true_lets_unmarked_function_build_with_no_warning(example_app: Path, monkeypatch):
    """With explicit_optin true, an unmarked function is a private helper:
    not exposed, but also not a hygiene violation. The build must succeed
    cleanly, and the function must not appear in the remote assets."""
    (example_app / "app" / "remote").mkdir(parents=True, exist_ok=True)
    (example_app / "app" / "remote" / "__init__.py").write_text("")
    (example_app / "app" / "remote" / "versions.py").write_text(
        "def insert_version(x: str) -> str: return x\n"
    )
    (example_app / "fymo.yml").write_text(
        (example_app / "fymo.yml").read_text() + "\nremote:\n  explicit_optin: true\n"
    )
    monkeypatch.setattr("fymo.build.prepare.shutil.which", lambda cmd: "/usr/bin/node")
    dist_dir = example_app / "dist"
    cache_dir = example_app / ".fymo" / "entries"
    config = prepare_build_config(example_app, dist_dir, cache_dir, dev=True)
    assert isinstance(config, BuildConfig)
    # No exposed functions in versions.py at all under explicit_optin -> the
    # module contributes nothing to remote_assets (see prepare's `if not
    # fns: continue`), so it must not appear as a key.
    assert "versions" not in config.remote_assets


def test_mode_strict_lets_unmarked_function_build_with_no_warning(example_app: Path, monkeypatch, capsys):
    """remote.mode: strict must enforce identically to explicit_optin: true:
    build succeeds, the unmarked function stays a private helper, and no
    deprecation warning is printed for the new spelling."""
    (example_app / "app" / "remote").mkdir(parents=True, exist_ok=True)
    (example_app / "app" / "remote" / "__init__.py").write_text("")
    (example_app / "app" / "remote" / "versions.py").write_text(
        "def insert_version(x: str) -> str: return x\n"
    )
    (example_app / "fymo.yml").write_text(
        (example_app / "fymo.yml").read_text() + "\nremote:\n  mode: strict\n"
    )
    monkeypatch.setattr("fymo.build.prepare.shutil.which", lambda cmd: "/usr/bin/node")
    dist_dir = example_app / "dist"
    cache_dir = example_app / ".fymo" / "entries"
    config = prepare_build_config(example_app, dist_dir, cache_dir, dev=True)
    assert isinstance(config, BuildConfig)
    assert "versions" not in config.remote_assets
    out = capsys.readouterr().out
    assert "deprecat" not in out.lower()


def test_mode_implicit_legacy_lets_unmarked_function_build(example_app: Path, monkeypatch):
    """remote.mode: implicit-legacy must silence the hygiene check identically
    to allow_implicit: true today."""
    (example_app / "app" / "remote").mkdir(parents=True, exist_ok=True)
    (example_app / "app" / "remote" / "__init__.py").write_text("")
    (example_app / "app" / "remote" / "versions.py").write_text(
        "def insert_version(x: str) -> str: return x\n"
    )
    (example_app / "fymo.yml").write_text(
        (example_app / "fymo.yml").read_text() + "\nremote:\n  mode: implicit-legacy\n"
    )
    monkeypatch.setattr("fymo.build.prepare.shutil.which", lambda cmd: "/usr/bin/node")
    dist_dir = example_app / "dist"
    cache_dir = example_app / ".fymo" / "entries"
    config = prepare_build_config(example_app, dist_dir, cache_dir, dev=True)
    assert isinstance(config, BuildConfig)


def test_invalid_remote_mode_raises_build_error(example_app: Path):
    """remote.mode: <bogus value> must surface as a BuildError naming the bad
    value, not a raw RemoteModeConfigError escaping to the CLI."""
    (example_app / "fymo.yml").write_text(
        (example_app / "fymo.yml").read_text() + "\nremote:\n  mode: bogus\n"
    )
    dist_dir = example_app / "dist"
    cache_dir = example_app / ".fymo" / "entries"
    with pytest.raises(BuildError, match="bogus"):
        prepare_build_config(example_app, dist_dir, cache_dir, dev=False)


def test_deprecated_explicit_optin_prints_deprecation_warning(example_app: Path, monkeypatch, capsys):
    """remote.explicit_optin (deprecated spelling) must trigger a non-fatal
    build-time warning pointing at remote.mode."""
    (example_app / "fymo.yml").write_text(
        (example_app / "fymo.yml").read_text() + "\nremote:\n  explicit_optin: true\n"
    )
    monkeypatch.setattr("fymo.build.prepare.shutil.which", lambda cmd: "/usr/bin/node")
    dist_dir = example_app / "dist"
    cache_dir = example_app / ".fymo" / "entries"
    prepare_build_config(example_app, dist_dir, cache_dir, dev=True)
    out = capsys.readouterr().out
    assert "explicit_optin" in out
    assert "remote.mode" in out


def test_mode_strict_prints_no_deprecation_warning(example_app: Path, monkeypatch, capsys):
    (example_app / "fymo.yml").write_text(
        (example_app / "fymo.yml").read_text() + "\nremote:\n  mode: strict\n"
    )
    monkeypatch.setattr("fymo.build.prepare.shutil.which", lambda cmd: "/usr/bin/node")
    dist_dir = example_app / "dist"
    cache_dir = example_app / ".fymo" / "entries"
    prepare_build_config(example_app, dist_dir, cache_dir, dev=True)
    out = capsys.readouterr().out
    assert "explicit_optin" not in out
    assert "remote.mode" not in out


@pytest.mark.usefixtures("node_available")
def test_prepare_build_config_reflects_blog_app_facts(blog_app: Path):
    """blog_app has index/, posts/ (with a resource _layout.svelte and
    show.svelte), tags/ (show.svelte, no resource layout), and
    redirect_demo/ (index.svelte, a standalone demo of fymo.remote.Redirect
    -- see tests/integration/test_redirect_hydration.py), plus a root
    _layout.svelte -- so this pins the known shape of what prepare must
    produce for both `fymo build` and `fymo dev` to agree on."""
    dist_dir = blog_app / "dist"
    cache_dir = blog_app / ".fymo" / "entries"

    config = prepare_build_config(blog_app, dist_dir, cache_dir, dev=False)

    assert isinstance(config, BuildConfig)

    route_names = {r.name for r in config.routes}
    assert route_names == {"index", "posts", "tags", "redirect_demo"}

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
