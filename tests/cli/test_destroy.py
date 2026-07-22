"""`fymo destroy page/remote/resource` (issue #89 round 3): generation
is reversible, fymo-brand safe.

Destroy deletes only files that are byte-identical to a pristine render
of the current templates (either variant), refuses loudly on anything
modified since generation unless --force, removes the empty directories
generation created but never shared ones (tests/conftest.py is never
removed), and reverses route injection with the same reparse-and-compare
guard used to inject.
"""
from pathlib import Path

import pytest
import yaml

from fymo.cli.commands.destroy import destroy_page, destroy_remote, destroy_resource
from fymo.cli.commands.generators import generate_page, generate_remote, generate_resource


def _scaffold_yml() -> str:
    from fymo.cli.commands._scaffold import render_fymo_yml
    return render_fymo_yml("sample_app", signin_route=True)


def _project(tmp_path: Path, auth: bool = True, seed_conftest: bool = True) -> Path:
    (tmp_path / "fymo.yml").write_text(_scaffold_yml())
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text('"""Application package"""')
    # Standing scaffold directories every real project has.
    (tmp_path / "app" / "controllers").mkdir()
    (tmp_path / "app" / "templates").mkdir()
    if auth:
        (tmp_path / "app" / "auth").mkdir()
    if seed_conftest:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "conftest.py").write_text("# app-owned conftest\n")
    return tmp_path


def _snapshot(root: Path):
    files = {}
    dirs = set()
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if "__pycache__" in rel:
            continue
        if p.is_dir():
            dirs.add(rel)
        else:
            files[rel] = p.read_bytes()
    return files, dirs


# --------------- snapshot identity ---------------


def test_destroy_reverses_generate_resource(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    before = _snapshot(project)
    monkeypatch.chdir(project)
    generate_resource("articles")
    destroy_resource("articles")
    assert _snapshot(project) == before
    out = capsys.readouterr().out
    assert "Removed" in out


def test_destroy_reverses_generate_page(tmp_path, monkeypatch):
    project = _project(tmp_path)
    before = _snapshot(project)
    monkeypatch.chdir(project)
    generate_page("about")
    destroy_page("about")
    assert _snapshot(project) == before


def test_destroy_reverses_generate_remote(tmp_path, monkeypatch):
    project = _project(tmp_path)
    before = _snapshot(project)
    monkeypatch.chdir(project)
    generate_remote("notes")
    destroy_remote("notes")
    assert _snapshot(project) == before


def test_destroy_reverses_read_only_resource(tmp_path, monkeypatch):
    project = _project(tmp_path, auth=False)
    before = _snapshot(project)
    monkeypatch.chdir(project)
    generate_resource("articles")
    destroy_resource("articles")
    assert _snapshot(project) == before


# --------------- safety ---------------


def test_destroy_refuses_modified_files_without_force(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    generate_resource("articles")
    controller = project / "app" / "controllers" / "articles.py"
    controller.write_text(controller.read_text() + "\n# my edit\n")
    fymo_yml_before = (project / "fymo.yml").read_text()

    with pytest.raises(SystemExit):
        destroy_resource("articles")
    combined = "".join(capsys.readouterr())
    assert "app/controllers/articles.py" in combined
    assert "modified since generation" in combined
    # All-or-nothing: nothing was deleted, the route stayed.
    assert (project / "app" / "remote" / "articles.py").is_file()
    assert controller.is_file()
    assert (project / "fymo.yml").read_text() == fymo_yml_before


def test_destroy_force_deletes_modified_files(tmp_path, monkeypatch):
    project = _project(tmp_path)
    before = _snapshot(project)
    monkeypatch.chdir(project)
    generate_resource("articles")
    controller = project / "app" / "controllers" / "articles.py"
    controller.write_text(controller.read_text() + "\n# my edit\n")
    destroy_resource("articles", force=True)
    assert _snapshot(project) == before


def test_destroy_never_removes_a_generated_conftest(tmp_path, monkeypatch):
    """tests/conftest.py is shared surface even when generation created
    it; destroy leaves it (and the tests/ dir holding it) alone."""
    project = _project(tmp_path, seed_conftest=False)
    monkeypatch.chdir(project)
    generate_remote("notes")
    destroy_remote("notes")
    assert (project / "tests" / "conftest.py").is_file()
    assert not (project / "tests" / "test_notes_remote.py").exists()
    assert not (project / "app" / "remote").exists()


def test_destroy_keeps_app_remote_when_other_modules_exist(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    generate_remote("notes")
    generate_remote("gadgets")
    destroy_remote("notes")
    assert not (project / "app" / "remote" / "notes.py").exists()
    assert (project / "app" / "remote" / "gadgets.py").is_file()
    assert (project / "app" / "remote" / "__init__.py").is_file()


def test_destroy_dry_run_prints_plan_and_touches_nothing(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    generate_resource("articles")
    after_generate = _snapshot(project)
    destroy_resource("articles", dry_run=True)
    assert _snapshot(project) == after_generate
    out = capsys.readouterr().out
    assert "would delete" in out
    assert "app/controllers/articles.py" in out
    assert "app/remote/articles.py" in out
    assert "fymo.yml" in out


def test_destroy_missing_files_is_not_an_error(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    destroy_page("ghost")
    out = capsys.readouterr().out
    assert "ghost" in out


# --------------- route removal guard ---------------


def test_destroy_page_route_removal_is_guarded(tmp_path, monkeypatch, capsys):
    """A routes block that no longer matches the scaffold shape gets the
    exact line to remove instead of an edit."""
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    generate_page("about")
    mangled = "name: sample_app\nroutes: {root: home.index, signin: signin.index, about: about.index}\n"
    (project / "fymo.yml").write_text(mangled)
    destroy_page("about")
    assert (project / "fymo.yml").read_text() == mangled
    out = capsys.readouterr().out
    assert "about: about.index" in out


def test_destroy_resource_removes_only_its_resources_entry(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    generate_resource("articles")
    destroy_resource("articles")
    data = yaml.safe_load((project / "fymo.yml").read_text())
    assert data["routes"]["resources"] == ["posts"]


# --------------- click surface ---------------


def test_cli_destroy_commands_wired(tmp_path):
    from click.testing import CliRunner
    from fymo.cli.main import cli

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _project(Path.cwd())
        result = runner.invoke(cli, ["generate", "resource", "articles"])
        assert result.exit_code == 0, result.output
        result = runner.invoke(cli, ["destroy", "resource", "articles"])
        assert result.exit_code == 0, result.output
        assert not (Path.cwd() / "app" / "remote").exists()
