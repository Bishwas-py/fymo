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
    for fn in ("list_notes", "create_notes", "get_notes", "update_notes", "delete_notes"):
        assert f"def {fn}(" in module, fn
    assert (project / "app" / "remote" / "__init__.py").is_file()

    test_file = (project / "tests" / "test_notes_remote.py").read_text()
    assert "from fymo.testing import acting_as, signed_in" in test_file
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


def test_remote_crud_semantics_through_fymo_testing(tmp_path, monkeypatch):
    """The generated CRUD teaches the repo's authorization conventions:
    reads are public, mutations require a session, and a row you do not
    own answers NotFound, never a distinguishable Forbidden."""
    from fymo.remote import NotFound
    from fymo.testing import acting_as, signed_in

    project = _project(tmp_path)
    monkeypatch.chdir(project)
    generate_remote("widgets")
    monkeypatch.syspath_prepend(str(project))
    _cleanup_app_modules()
    try:
        from app.remote.widgets import (
            create_widgets,
            delete_widgets,
            get_widgets,
            list_widgets,
            update_widgets,
        )

        assert get_widgets(1)["created_by"] == "seed"
        with pytest.raises(NotFound):
            get_widgets(999)

        with signed_in("u_alice") as ident:
            mine = create_widgets(title="Mine")
            renamed = update_widgets(mine["id"], title="Renamed")
            assert renamed["title"] == "Renamed"
            assert renamed["created_by"] == ident.uid

            # The seed row belongs to "seed", so a signed-in caller
            # genuinely does not own it.
            with pytest.raises(NotFound):
                update_widgets(1, title="steal")
            with pytest.raises(NotFound):
                delete_widgets(1)

            with acting_as("u_bob"):
                with pytest.raises(NotFound):
                    update_widgets(mine["id"], title="steal")
                with pytest.raises(NotFound):
                    delete_widgets(mine["id"])

            deleted = delete_widgets(mine["id"])
            assert deleted["id"] == mine["id"]
            assert all(row["id"] != mine["id"] for row in list_widgets())
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
        "app/templates/articles/show.svelte",
        "app/templates/articles/Item.svelte",
        "app/remote/articles.py",
        "tests/test_articles_remote.py",
        "tests/conftest.py",
    ):
        assert (project / rel).is_file(), rel

    data = yaml.safe_load((project / "fymo.yml").read_text())
    assert "articles" in data["routes"]["resources"]
    assert "articles" not in data["routes"]
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
        "app/templates/articles/show.svelte",
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


def test_resource_injects_a_resources_entry_and_show_route_resolves(tmp_path, monkeypatch, capsys):
    """A plain `name: name.index` route only covers /name; detail URLs
    exist through the Router's resources expansion, so generate resource
    injects into the resources list and /name/<id> resolves as a declared
    show route carrying the id param."""
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    generate_resource("articles")

    data = yaml.safe_load((project / "fymo.yml").read_text())
    assert data["routes"]["resources"] == ["articles", "posts"]

    router = Router(project / "fymo.yml")
    match = router.match("/articles/9")
    assert match["controller"] == "articles"
    assert match["action"] == "show"
    assert match["params"] == {"id": "9"}
    assert "convention" not in match
    index = router.match("/articles")
    assert index["controller"] == "articles"
    assert index["action"] == "index"
    assert "resources" in capsys.readouterr().out


def test_resource_creates_the_resources_block_when_absent(tmp_path, monkeypatch):
    project = _project(tmp_path)
    (project / "fymo.yml").write_text(
        "name: sample_app\nroutes:\n  root: home.index\n  signin: signin.index\n"
    )
    monkeypatch.chdir(project)
    generate_resource("articles")
    data = yaml.safe_load((project / "fymo.yml").read_text())
    assert data["routes"]["resources"] == ["articles"]
    assert data["routes"]["root"] == "home.index"
    match = Router(project / "fymo.yml").match("/articles/9")
    assert match["action"] == "show"


def test_resource_adapts_to_the_existing_list_indent(tmp_path, monkeypatch):
    project = _project(tmp_path)
    (project / "fymo.yml").write_text(
        "name: sample_app\nroutes:\n  root: home.index\n  signin: signin.index\n"
        "  resources:\n  - posts\n"
    )
    monkeypatch.chdir(project)
    generate_resource("articles")
    data = yaml.safe_load((project / "fymo.yml").read_text())
    assert data["routes"]["resources"] == ["articles", "posts"]


def test_resource_on_mangled_routes_prints_resources_lines(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    (project / "fymo.yml").write_text(
        "name: sample_app\nroutes: {root: home.index, signin: signin.index}\n"
    )
    before = (project / "fymo.yml").read_text()
    monkeypatch.chdir(project)
    generate_resource("articles")
    assert (project / "app" / "templates" / "articles" / "show.svelte").is_file()
    assert (project / "fymo.yml").read_text() == before
    out = capsys.readouterr().out
    assert "resources:" in out
    assert "- articles" in out


def test_resource_over_an_existing_plain_route_points_at_resources(tmp_path, monkeypatch, capsys):
    """A previously injected `name: name.index` route serves /name but not
    /name/<id>; the generator says so instead of silently leaving detail
    URLs dead."""
    project = _project(tmp_path)
    (project / "fymo.yml").write_text(
        "name: sample_app\nroutes:\n  root: home.index\n  signin: signin.index\n"
        "  articles: articles.index\n"
    )
    before = (project / "fymo.yml").read_text()
    monkeypatch.chdir(project)
    generate_resource("articles")
    assert (project / "fymo.yml").read_text() == before
    out = capsys.readouterr().out
    assert "already" in out.lower()
    assert "resources" in out


def test_resource_show_and_item_render_through_index(tmp_path, monkeypatch):
    """The build produces one rendered entry per template directory
    (index.svelte wins over show.svelte in fymo.build.discovery), so the
    generated show page must be reachable through index.svelte, not sit
    beside it as a dead second entry."""
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    generate_resource("articles")
    index = (project / "app" / "templates" / "articles" / "index.svelte").read_text()
    assert "import Show from './show.svelte'" in index
    assert "item_id" in index
    show = (project / "app" / "templates" / "articles" / "show.svelte").read_text()
    assert "get_articles" in show
    assert "update_articles" in show
    assert "delete_articles" in show
    assert "$identity" in show
    controller = (project / "app" / "controllers" / "articles.py").read_text()
    assert "def getContext(id" in controller
    assert "item_id" in controller
    item = (project / "app" / "templates" / "articles" / "Item.svelte").read_text()
    assert 'href="/articles/{item.id}"' in item


# --------------- no-auth project guard ---------------


def test_resource_warns_when_the_project_has_no_auth(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    monkeypatch.chdir(project)
    generate_resource("articles")
    out = capsys.readouterr().out
    assert "fymo generate auth" in out
    assert "401" in out
    assert (project / "app" / "remote" / "articles.py").is_file()


def test_no_auth_warning_does_not_fire_in_an_auth_project(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    (project / "app" / "auth").mkdir()
    (project / "app" / "auth" / "resolver.py").write_text("# resolver\n")
    monkeypatch.chdir(project)
    generate_resource("articles")
    assert "fymo generate auth" not in capsys.readouterr().out


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
