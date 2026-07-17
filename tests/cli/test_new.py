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
