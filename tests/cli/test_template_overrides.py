"""User-overridable generator templates (issue #89 round 3).

Lookup order: <project>/.fymo/templates/<relpath> wins over the template
packaged in fymo, everything else identical (tokens, writer, conflict
modes). `fymo generate templates` publishes the packaged tree into
.fymo/templates/ for editing, through the same conflict writer.
"""
from pathlib import Path

import pytest

from fymo.cli.commands.generators import generate_page, publish_templates

PACKAGED = Path(__file__).resolve().parents[2] / "fymo" / "cli" / "templates"


def _project(tmp_path: Path) -> Path:
    from fymo.cli.commands._scaffold import render_fymo_yml
    (tmp_path / "fymo.yml").write_text(render_fymo_yml("sample_app", signin_route=True))
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text('"""Application package"""')
    (tmp_path / "app" / "auth").mkdir()
    return tmp_path


def test_override_changes_generate_output(tmp_path, monkeypatch):
    project = _project(tmp_path)
    override = project / ".fymo" / "templates" / "page" / "controller.py.tmpl"
    override.parent.mkdir(parents=True)
    override.write_text(
        '"""My house controller style."""\n\n\n'
        "def getContext():\n"
        "    return {'name': '__fymo_tmpl_name__'}\n"
    )
    monkeypatch.chdir(project)
    generate_page("about")
    content = (project / "app" / "controllers" / "about.py").read_text()
    assert "My house controller style" in content
    assert "'name': 'about'" in content
    # Non-overridden templates still come from the package.
    index = (project / "app" / "templates" / "about" / "index.svelte").read_text()
    assert "$props()" in index


def test_override_applies_to_generate_auth(tmp_path, monkeypatch):
    from fymo.cli.commands.generate_auth import generate_auth

    project = _project(tmp_path)
    (project / "app" / "auth").rmdir()
    override = project / ".fymo" / "templates" / "auth" / "skeleton" / "resolver.py.tmpl"
    override.parent.mkdir(parents=True)
    override.write_text("# my resolver stub\n")
    monkeypatch.chdir(project)
    generate_auth("skeleton")
    assert (project / "app" / "auth" / "resolver.py").read_text() == "# my resolver stub\n"


def test_publish_templates_copies_the_packaged_tree(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    publish_templates()
    published = sorted(
        p.relative_to(project / ".fymo" / "templates").as_posix()
        for p in (project / ".fymo" / "templates").rglob("*.tmpl")
    )
    packaged = sorted(p.relative_to(PACKAGED).as_posix() for p in PACKAGED.rglob("*.tmpl"))
    assert published == packaged
    rel = "page/controller.py.tmpl"
    assert (project / ".fymo" / "templates" / rel).read_bytes() == (PACKAGED / rel).read_bytes()


def test_publish_refuses_over_existing_without_force(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    existing = project / ".fymo" / "templates" / "page" / "controller.py.tmpl"
    existing.parent.mkdir(parents=True)
    existing.write_text("# edited\n")
    monkeypatch.chdir(project)
    with pytest.raises(SystemExit):
        publish_templates()
    assert ".fymo/templates/page/controller.py.tmpl" in "".join(capsys.readouterr())
    assert existing.read_text() == "# edited\n"
    publish_templates(force=True)
    assert existing.read_text() == (PACKAGED / "page" / "controller.py.tmpl").read_text()


def test_publish_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    publish_templates(dry_run=True)
    assert not (project / ".fymo").exists()
    assert "would create" in capsys.readouterr().out


def test_cli_generate_templates_wired(tmp_path):
    from click.testing import CliRunner
    from fymo.cli.main import cli

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _project(Path.cwd())
        result = runner.invoke(cli, ["generate", "templates"])
        assert result.exit_code == 0, result.output
        assert (Path.cwd() / ".fymo" / "templates" / "page" / "controller.py.tmpl").is_file()
