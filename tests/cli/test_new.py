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


def test_new_scaffold_defaults_to_explicit_remote_optin(tmp_path):
    """Issue #8: fresh projects should require @remote to expose a function,
    not fall back to implicit file-placement exposure. Existing projects are
    unaffected: this only changes what NEW projects generate."""
    from fymo.cli.commands._scaffold import render_fymo_yml
    import yaml
    content = render_fymo_yml("sample_app")
    data = yaml.safe_load(content)
    assert data["remote"]["explicit_optin"] is True


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
