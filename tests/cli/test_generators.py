"""`fymo generate page/remote/resource` (issue #89 phase 4).

The daily-loop generators: a routed page, a remote module with a test
that exercises it through fymo.testing, and both composed as a resource.
Route wiring is the one injection problem: fymo.yml is what the router
actually reads in scaffolded projects (fymo.yml wins over config/routes.py
in FymoApp._initialize_router), so injection targets its routes block,
and only when the block matches the shape fymo's own scaffold produces;
anything else gets the exact line to add, printed, with the files still
generated. Never a half-write, never a silent skip.
"""
import sys
from pathlib import Path

import pytest
import yaml

from fymo.cli.commands.generators import generate_page, generate_remote, generate_resource
from fymo.core.router import Router


def _scaffold_yml() -> str:
    from fymo.cli.commands._scaffold import render_fymo_yml
    return render_fymo_yml("sample_app", signin_route=True)


def _project(tmp_path: Path) -> Path:
    (tmp_path / "fymo.yml").write_text(_scaffold_yml())
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text('"""Application package"""')
    return tmp_path


def _cleanup_app_modules() -> None:
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


# --------------- name validation ---------------


@pytest.mark.parametrize("bad", [
    "Posts", "my-page", "posts/evil", "../evil", "1abc", "class", "auth", "signin", "root", "",
    "resources",
])
def test_invalid_names_are_rejected_loudly(bad, tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    with pytest.raises(SystemExit):
        generate_page(bad)
    assert not (project / "app" / "controllers").exists()
    combined = "".join(capsys.readouterr())
    assert bad in combined or "name" in combined.lower()


def test_generators_refuse_outside_a_fymo_project(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        generate_page("about")
    assert "fymo.yml" in "".join(capsys.readouterr())


# --------------- generate page ---------------


def test_page_writes_controller_template_and_injects_route(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    generate_page("about")

    controller = (project / "app" / "controllers" / "about.py").read_text()
    assert "def getContext(" in controller
    template = (project / "app" / "templates" / "about" / "index.svelte").read_text()
    assert "$props()" in template
    assert "__fymo_tmpl_" not in controller + template

    data = yaml.safe_load((project / "fymo.yml").read_text())
    assert data["routes"]["about"] == "about.index"
    out = capsys.readouterr().out
    assert "about: about.index" in out
    assert "inject" in out.lower()


def test_page_route_resolves_as_a_declared_route(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    generate_page("about")
    match = Router(project / "fymo.yml").match("/about")
    assert match["controller"] == "about"
    assert match["action"] == "index"
    assert "convention" not in match


def test_page_injection_only_adds_the_one_route(tmp_path, monkeypatch):
    project = _project(tmp_path)
    before = yaml.safe_load((project / "fymo.yml").read_text())
    monkeypatch.chdir(project)
    generate_page("about")
    after = yaml.safe_load((project / "fymo.yml").read_text())
    before["routes"]["about"] = "about.index"
    assert after == before


def test_page_on_mangled_routes_prints_exact_lines_and_still_generates(
    tmp_path, monkeypatch, capsys
):
    project = _project(tmp_path)
    (project / "fymo.yml").write_text(
        "name: sample_app\nroutes: {root: home.index, signin: signin.index}\n"
    )
    before = (project / "fymo.yml").read_text()
    monkeypatch.chdir(project)
    generate_page("about")

    assert (project / "app" / "controllers" / "about.py").is_file()
    assert (project / "app" / "templates" / "about" / "index.svelte").is_file()
    assert (project / "fymo.yml").read_text() == before
    out = capsys.readouterr().out
    assert "about: about.index" in out
    assert "fymo.yml" in out


def test_page_already_routed_reports_and_leaves_fymo_yml_alone(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    before = (project / "fymo.yml").read_text()
    monkeypatch.chdir(project)
    generate_page("posts")
    assert (project / "app" / "controllers" / "posts.py").is_file()
    assert (project / "fymo.yml").read_text() == before
    assert "already" in capsys.readouterr().out.lower()


def test_page_refuses_on_existing_controller_and_writes_nothing(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    (project / "app" / "controllers").mkdir()
    (project / "app" / "controllers" / "about.py").write_text("mine\n")
    before = (project / "fymo.yml").read_text()
    monkeypatch.chdir(project)
    with pytest.raises(SystemExit):
        generate_page("about")
    combined = "".join(capsys.readouterr())
    assert "app/controllers/about.py" in combined
    assert (project / "app" / "controllers" / "about.py").read_text() == "mine\n"
    assert not (project / "app" / "templates" / "about").exists()
    assert (project / "fymo.yml").read_text() == before


def test_page_dry_run_lists_everything_and_writes_nothing(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    before = (project / "fymo.yml").read_text()
    monkeypatch.chdir(project)
    generate_page("about", dry_run=True)
    out = capsys.readouterr().out
    assert "app/controllers/about.py" in out
    assert "app/templates/about/index.svelte" in out
    assert "would create" in out
    assert "would update" in out
    assert not (project / "app" / "controllers").exists()
    assert (project / "fymo.yml").read_text() == before


def test_page_diff_shows_route_injection_and_writes_nothing(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    before = (project / "fymo.yml").read_text()
    monkeypatch.chdir(project)
    generate_page("about", diff=True)
    out = capsys.readouterr().out
    assert "+  about: about.index" in out
    assert (project / "fymo.yml").read_text() == before
    assert not (project / "app" / "controllers").exists()


# --------------- generate remote ---------------


def test_remote_writes_module_test_and_conftest(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    generate_remote("notes")

    module = (project / "app" / "remote" / "notes.py").read_text()
    assert "@remote" in module
    assert "def list_notes(" in module
    assert "def create_notes(" in module
    assert (project / "app" / "remote" / "__init__.py").is_file()

    test_file = (project / "tests" / "test_notes_remote.py").read_text()
    assert "from fymo.testing import signed_in" in test_file
    assert "from app.remote.notes import" in test_file
    conftest = (project / "tests" / "conftest.py").read_text()
    assert "sys.path" in conftest

    for rel in ("app/remote/notes.py", "tests/test_notes_remote.py", "tests/conftest.py"):
        text = (project / rel).read_text()
        assert "__fymo_tmpl_" not in text, rel
        compile(text, rel, "exec")


def test_remote_keeps_an_existing_conftest(tmp_path, monkeypatch):
    project = _project(tmp_path)
    (project / "tests").mkdir()
    (project / "tests" / "conftest.py").write_text("# mine\n")
    monkeypatch.chdir(project)
    generate_remote("notes")
    assert (project / "tests" / "conftest.py").read_text() == "# mine\n"
    assert (project / "tests" / "test_notes_remote.py").is_file()


def test_remote_generated_functions_work_through_fymo_testing(tmp_path, monkeypatch):
    from fymo.testing import signed_in

    project = _project(tmp_path)
    monkeypatch.chdir(project)
    generate_remote("notes")
    monkeypatch.syspath_prepend(str(project))
    _cleanup_app_modules()
    try:
        from app.remote.notes import create_notes, list_notes

        assert any(item["created_by"] == "seed" for item in list_notes())
        with signed_in("u_alice") as ident:
            item = create_notes(title="hello")
        assert item["created_by"] == ident.uid
    finally:
        _cleanup_app_modules()


# --------------- generate resource ---------------


def test_resource_composes_page_and_remote_in_one_run(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    generate_resource("articles")

    for rel in (
        "app/controllers/articles.py",
        "app/templates/articles/index.svelte",
        "app/remote/articles.py",
        "tests/test_articles_remote.py",
        "tests/conftest.py",
    ):
        assert (project / rel).is_file(), rel

    data = yaml.safe_load((project / "fymo.yml").read_text())
    assert data["routes"]["articles"] == "articles.index"
    out = capsys.readouterr().out
    assert out.count("Generated") == 1


def test_resource_dry_run_lists_every_path_and_writes_nothing(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    before = (project / "fymo.yml").read_text()
    monkeypatch.chdir(project)
    generate_resource("articles", dry_run=True)
    out = capsys.readouterr().out
    for rel in (
        "app/controllers/articles.py",
        "app/templates/articles/index.svelte",
        "app/remote/articles.py",
        "tests/test_articles_remote.py",
        "fymo.yml",
    ):
        assert rel in out, rel
    assert not (project / "app" / "controllers").exists()
    assert not (project / "app" / "remote").exists()
    assert not (project / "tests").exists()
    assert (project / "fymo.yml").read_text() == before


def test_resource_refusal_is_all_or_nothing(tmp_path, monkeypatch):
    project = _project(tmp_path)
    (project / "app" / "remote").mkdir(parents=True)
    (project / "app" / "remote" / "articles.py").write_text("mine\n")
    before = (project / "fymo.yml").read_text()
    monkeypatch.chdir(project)
    with pytest.raises(SystemExit):
        generate_resource("articles")
    assert not (project / "app" / "controllers").exists()
    assert not (project / "tests").exists()
    assert (project / "fymo.yml").read_text() == before


# --------------- click surface ---------------


def test_cli_generate_page_remote_resource_wired(tmp_path):
    from click.testing import CliRunner
    from fymo.cli.main import cli

    runner = CliRunner()
    for args, marker in (
        (["generate", "page", "about"], "app/controllers/about.py"),
        (["generate", "remote", "notes"], "app/remote/notes.py"),
        (["generate", "resource", "articles"], "app/remote/articles.py"),
    ):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _project(Path.cwd())
            result = runner.invoke(cli, args)
            assert result.exit_code == 0, result.output
            assert (Path.cwd() / marker).is_file()


def test_cli_generate_page_conflict_flags_mutually_exclusive(tmp_path):
    from click.testing import CliRunner
    from fymo.cli.main import cli

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _project(Path.cwd())
        result = runner.invoke(cli, ["generate", "page", "about", "--force", "--diff"])
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output
