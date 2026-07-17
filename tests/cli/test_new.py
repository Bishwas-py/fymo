"""Tests for `fymo new` project scaffolding."""
from pathlib import Path
import json

from fymo.cli.commands.new import create_project


def test_scaffolds_app_lib_and_app_components_dirs(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    assert (tmp_path / "myapp" / "app" / "lib").is_dir()
    assert (tmp_path / "myapp" / "app" / "components").is_dir()


def test_scaffolds_app_support_dir_with_init(tmp_path: Path, monkeypatch):
    """app/support/ is the Python-only home for shared server-side utilities
    that don't fit controllers/remote/jobs/broadcasts/lib, see
    docs/conventions.md. It needs __init__.py like the other app/
    subpackages so it's importable as app.support.* right away."""
    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    support_dir = tmp_path / "myapp" / "app" / "support"
    assert support_dir.is_dir()
    assert (support_dir / "__init__.py").is_file()


def test_scaffolds_tsconfig_with_lib_components_and_remote_aliases(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    tsconfig_path = tmp_path / "myapp" / "tsconfig.json"
    assert tsconfig_path.is_file()
    data = json.loads(tsconfig_path.read_text())
    paths = data["compilerOptions"]["paths"]
    assert paths["$lib/*"] == ["./app/lib/*"]
    assert paths["$components/*"] == ["./app/components/*"]
    assert paths["$remote/*"] == ["./dist/client/_remote/*"]
    assert paths["$fymo/*"] == ["./dist/client/_fymo/*"]
    # No separate server-only alias: the server/client boundary in fymo is
    # language, not directory convention -- app/controllers/*.py and
    # app/remote/*.py are server-only by construction (Python never reaches
    # the client bundle), so there's nothing under app/lib/ that needs its
    # own guarded sub-path.
    assert not any("server" in key for key in paths)


def test_new_and_init_scaffold_identical_fymo_yml(tmp_path):
    """fymo new and fymo init must scaffold the same fymo.yml — they had
    silently drifted (init was missing the build: block). Audit finding #6."""
    from fymo.cli.commands._scaffold import render_fymo_yml
    content = render_fymo_yml("sample_app")
    assert "routes:" in content
    assert "build:" in content
    assert "sample_app" in content


def test_new_scaffold_defaults_to_remote_mode_strict(tmp_path):
    """Issue #8: fresh projects should require @remote to expose a function,
    not fall back to implicit file-placement exposure. Existing projects are
    unaffected: this only changes what NEW projects generate.

    Issue #25: new projects must be scaffolded on the current remote.mode
    spelling, not the deprecated explicit_optin boolean."""
    from fymo.cli.commands._scaffold import render_fymo_yml
    import yaml
    content = render_fymo_yml("sample_app")
    data = yaml.safe_load(content)
    assert data["remote"]["mode"] == "strict"
    assert "explicit_optin" not in data["remote"]


def test_new_does_not_scaffold_dead_config_routes(tmp_path, monkeypatch):
    """new.py used to ship config/routes.py into every project, but the
    router only ever reads it when fymo.yml is ABSENT — and new.py always
    writes fymo.yml, so the file was unreachable by construction."""
    from fymo.cli.commands.new import create_project
    monkeypatch.chdir(tmp_path)
    create_project("deadfile_check")
    project = tmp_path / "deadfile_check"
    assert (project / "fymo.yml").is_file()
    assert not (project / "config" / "routes.py").exists()


def test_new_scaffolds_server_py_as_plain_wsgi_entrypoint(tmp_path, monkeypatch):
    """Issue #26: server.py's `if __name__ == "__main__":` block called
    run_dev_server(app) directly, a path that never set dev=True or
    FYMO_DEV and bypassed fymo dev's watcher/esbuild/sidecar pipeline
    entirely. Generated server.py is now just the WSGI entrypoint, for
    handing to gunicorn/uwsgi or `fymo serve --prod`; `fymo dev` (or its
    `fymo serve` alias) is the one true way to run it locally."""
    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    content = (tmp_path / "myapp" / "server.py").read_text()
    assert "create_app" in content
    assert "__main__" not in content
    assert "run_dev_server" not in content


def test_new_prints_fymo_dev_as_next_step(tmp_path, monkeypatch, capsys):
    """Next-steps output should point at the command that's actually named
    for what it does, not the alias."""
    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    out = capsys.readouterr().out
    assert "fymo dev" in out


def test_new_scaffolds_package_json_dev_script_using_fymo_dev(tmp_path, monkeypatch):
    import json
    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    package_json = json.loads((tmp_path / "myapp" / "package.json").read_text())
    assert package_json["scripts"]["dev"] == "fymo dev"


def test_new_scaffolds_favicon_svg_in_app_static(tmp_path, monkeypatch):
    """Issue #75: a fresh project serves its own favicon out of the box via
    the root-static allowlist. SVG only, one file, no .ico."""
    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    favicon = tmp_path / "myapp" / "app" / "static" / "favicon.svg"
    assert favicon.is_file()
    content = favicon.read_text()
    assert content.startswith("<svg")
    assert "<text" not in content


def test_new_scaffolds_root_layout_with_favicon_link(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    layout = tmp_path / "myapp" / "app" / "templates" / "_layout.svelte"
    assert layout.is_file()
    content = layout.read_text()
    assert "<svelte:head>" in content
    assert 'rel="icon"' in content
    assert 'type="image/svg+xml"' in content
    assert 'href="/favicon.svg"' in content
    # It's a layout: it must render its children.
    assert "children" in content


AUTH_SCAFFOLD_FILES = [
    "app/auth/__init__.py",
    "app/auth/resolver.py",
    "app/auth/store.py",
    "app/auth/extras.py",
    "app/auth/public.py",
    "app/remote/__init__.py",
    "app/remote/auth.py",
    "schema/users.sql",
    "app/controllers/signin.py",
    "app/templates/signin/index.svelte",
]


def test_new_scaffolds_working_password_auth_by_default(tmp_path, monkeypatch):
    """Issue #80 phase 5: a fresh `fymo new` project reaches a working login
    with zero extra steps. The full password auth file set plus the signin
    page are part of the default scaffold."""
    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    project = tmp_path / "myapp"
    for rel in AUTH_SCAFFOLD_FILES:
        assert (project / rel).is_file(), f"missing {rel}"


def test_new_auth_files_are_the_generate_auth_templates(tmp_path, monkeypatch):
    """fymo new must reuse the exact `fymo generate auth` code path, not a
    parallel copy of the templates: the rendered files are byte-identical
    to the password variant's template sources."""
    from fymo.cli.commands.generate_auth import _TEMPLATES_DIR, _VARIANT_FILES

    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    project = tmp_path / "myapp"
    for tmpl_rel, out_rel in _VARIANT_FILES["password"].items():
        assert (project / out_rel).read_text() == (_TEMPLATES_DIR / tmpl_rel).read_text()


def test_new_fymo_yml_routes_signin(tmp_path, monkeypatch):
    import yaml
    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    data = yaml.safe_load((tmp_path / "myapp" / "fymo.yml").read_text())
    assert data["routes"]["signin"] == "signin.index"


def test_new_fymo_yml_mentions_require_auth_in_comments_only(tmp_path, monkeypatch):
    """The default scaffold ships no active require_auth: it must boot
    without opinions about what to protect. require_auth appears in the
    fymo.yml comment block only, matching the file's existing comment style."""
    import yaml
    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    content = (tmp_path / "myapp" / "fymo.yml").read_text()
    assert "require_auth" in content
    data = yaml.safe_load(content)
    assert "require_auth" not in str(data)


def test_new_signin_template_wires_remote_auth_and_identity(tmp_path, monkeypatch):
    """The signin page calls the generated remote functions and reads the
    $fymo/auth identity store; login carries the ?next= path require_auth
    redirects arrive with. The remote callables are threaded through the
    controller context as props (the SSR pass deliberately externalizes
    $remote/*, so a top-level value import would break the SSR module;
    blog_app's Comments flow is the reference for this pattern)."""
    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    project = tmp_path / "myapp"
    controller = (project / "app" / "controllers" / "signin.py").read_text()
    assert "from app.remote.auth import" in controller
    assert "'login': login" in controller
    assert "'signup': signup" in controller
    content = (project / "app" / "templates" / "signin" / "index.svelte").read_text()
    assert "$fymo/auth" in content
    assert "login" in content
    assert "signup" in content
    assert "next" in content
    assert "from '$remote" not in content


def test_new_controllers_use_get_context_convention(tmp_path, monkeypatch):
    """The runtime reads getContext()/getDoc() from controllers
    (fymo/core/ssr_controller.py); a module-level `context` dict is never
    consulted, so a scaffold shipping one renders empty props. Both
    scaffolded controllers must use the real convention."""
    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    for name in ("home", "signin"):
        content = (tmp_path / "myapp" / "app" / "controllers" / f"{name}.py").read_text()
        assert "def getContext(" in content, name
        assert "\ncontext = " not in content, name


def test_new_gitignore_ignores_data_dir(tmp_path, monkeypatch):
    """The generated store keeps the sqlite db at data/app.db and its own
    docstring says to keep it out of git; the scaffold's .gitignore must
    actually do that."""
    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    gitignore = (tmp_path / "myapp" / ".gitignore").read_text()
    assert "/data/" in gitignore


def test_new_no_auth_skips_auth_scaffold(tmp_path, monkeypatch):
    import yaml
    monkeypatch.chdir(tmp_path)
    create_project("myapp", auth=False)
    project = tmp_path / "myapp"
    for rel in AUTH_SCAFFOLD_FILES:
        assert not (project / rel).exists(), f"unexpected {rel}"
    assert not (project / "app" / "auth").exists()
    assert not (project / "schema").exists()
    data = yaml.safe_load((project / "fymo.yml").read_text())
    assert "signin" not in data["routes"]


def test_cli_new_no_auth_flag(tmp_path):
    from click.testing import CliRunner
    from fymo.cli.main import cli

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["new", "myapp", "--no-auth"])
        assert result.exit_code == 0, result.output
        assert (Path.cwd() / "myapp" / "fymo.yml").is_file()
        assert not (Path.cwd() / "myapp" / "app" / "auth").exists()


def test_new_next_steps_reflect_scaffolded_auth(tmp_path, monkeypatch, capsys):
    """The default scaffold already contains working auth, so the printed
    next steps must say so and must not tell the user to run the generator."""
    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    out = capsys.readouterr().out
    assert "/signin" in out
    assert "generate auth" not in out


def test_new_no_auth_next_steps_point_at_generate_auth(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    create_project("myapp", auth=False)
    out = capsys.readouterr().out
    assert "fymo generate auth" in out
    assert "/signin" not in out


def test_default_scaffold_passes_page_auth_hygiene(tmp_path, monkeypatch):
    """No active require_auth in the scaffold means the require_auth-without-
    resolver check has nothing to fire on; pin that."""
    from fymo.build.hygiene import check_page_auth_hygiene

    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    assert check_page_auth_hygiene(tmp_path / "myapp") == []


def test_new_scaffolds_package_json_with_full_build_deps(tmp_path, monkeypatch):
    """Issue #55: a fresh `fymo new` project could never build. fymo/build/js/build.mjs
    requires esbuild-svelte and svelte-preprocess directly, and app/lib code commonly
    needs devalue and TypeScript, but the scaffolded package.json only ever listed
    svelte and esbuild. Bring it in line with examples/blog_app/package.json, the
    known-good reference every other build-time test in this repo relies on."""
    import json
    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    package_json = json.loads((tmp_path / "myapp" / "package.json").read_text())
    assert package_json["dependencies"]["devalue"] == "^5.8.1"
    assert package_json["dependencies"]["svelte"] == "^5.56.4"
    dev_deps = package_json["devDependencies"]
    assert dev_deps["esbuild"] == "^0.25.9"
    assert dev_deps["esbuild-svelte"] == "^0.9.0"
    assert dev_deps["svelte-preprocess"] == "^6.0.3"
    assert dev_deps["typescript"] == "^5.5.0"
