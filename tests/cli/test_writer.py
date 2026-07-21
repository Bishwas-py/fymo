"""Shared plan writer for every generator (issue #89 phase 2).

One conflict policy for all generators: default refuses loudly on any
existing target naming the file (generate auth's behavior and message
style), --force overwrites, --dry-run prints every path and writes
nothing, --diff prints unified diffs against existing files and writes
nothing. `update` entries are expected to exist (route injection edits
fymo.yml in place) and never trigger the refusal.
"""
from pathlib import Path

import pytest

from fymo.cli.writer import PlannedFile, execute_plan


def _plan():
    return [
        PlannedFile("app/controllers/posts.py", "def getContext():\n    return {}\n"),
        PlannedFile("app/templates/posts/index.svelte", "<h1>Posts</h1>\n"),
    ]


def test_writes_plan_creating_parents_and_returns_relpaths(tmp_path: Path):
    written = execute_plan(tmp_path, _plan(), command="fymo generate page")
    assert written == ["app/controllers/posts.py", "app/templates/posts/index.svelte"]
    assert (tmp_path / "app/controllers/posts.py").read_text().startswith("def getContext")
    assert (tmp_path / "app/templates/posts/index.svelte").read_text() == "<h1>Posts</h1>\n"


def test_chmod_applied_after_write(tmp_path: Path):
    execute_plan(tmp_path, [PlannedFile("server.py", "app = None\n", chmod=0o755)],
                 command="fymo new")
    assert (tmp_path / "server.py").stat().st_mode & 0o777 == 0o755


def test_refuses_on_any_existing_target_naming_each_file(tmp_path: Path, capsys):
    (tmp_path / "app" / "controllers").mkdir(parents=True)
    (tmp_path / "app" / "controllers" / "posts.py").write_text("mine\n")
    with pytest.raises(SystemExit):
        execute_plan(tmp_path, _plan(), command="fymo generate page")
    combined = "".join(capsys.readouterr())
    assert "app/controllers/posts.py" in combined
    assert "delete or move" in combined.lower()
    assert "fymo generate page" in combined
    # Refusal is all-or-nothing: the non-conflicting file was not written.
    assert not (tmp_path / "app" / "templates").exists()
    # And the existing file is untouched.
    assert (tmp_path / "app" / "controllers" / "posts.py").read_text() == "mine\n"


def test_force_overwrites_existing(tmp_path: Path):
    (tmp_path / "app" / "controllers").mkdir(parents=True)
    (tmp_path / "app" / "controllers" / "posts.py").write_text("mine\n")
    written = execute_plan(tmp_path, _plan(), command="fymo generate page", force=True)
    assert "app/controllers/posts.py" in written
    assert (tmp_path / "app/controllers/posts.py").read_text().startswith("def getContext")


def test_dry_run_prints_every_path_and_writes_nothing(tmp_path: Path, capsys):
    (tmp_path / "app" / "controllers").mkdir(parents=True)
    (tmp_path / "app" / "controllers" / "posts.py").write_text("mine\n")
    written = execute_plan(tmp_path, _plan(), command="fymo generate page", dry_run=True)
    assert written == []
    out = capsys.readouterr().out
    assert "app/controllers/posts.py" in out
    assert "app/templates/posts/index.svelte" in out
    assert "would overwrite" in out
    assert "would create" in out
    assert (tmp_path / "app" / "controllers" / "posts.py").read_text() == "mine\n"
    assert not (tmp_path / "app" / "templates").exists()


def test_diff_prints_unified_diff_and_writes_nothing(tmp_path: Path, capsys):
    (tmp_path / "app" / "controllers").mkdir(parents=True)
    (tmp_path / "app" / "controllers" / "posts.py").write_text("old_line\n")
    written = execute_plan(tmp_path, _plan(), command="fymo generate page", diff=True)
    assert written == []
    out = capsys.readouterr().out
    assert "--- " in out and "+++ " in out
    assert "-old_line" in out
    assert "+def getContext():" in out
    # New files have no diff to show; they are still listed.
    assert "app/templates/posts/index.svelte" in out
    assert (tmp_path / "app" / "controllers" / "posts.py").read_text() == "old_line\n"
    assert not (tmp_path / "app" / "templates").exists()


def test_diff_skips_identical_existing_file(tmp_path: Path, capsys):
    plan = _plan()
    target = tmp_path / plan[0].relpath
    target.parent.mkdir(parents=True)
    target.write_text(plan[0].content)
    execute_plan(tmp_path, plan, command="fymo generate page", diff=True)
    out = capsys.readouterr().out
    assert "-def getContext" not in out


def test_update_entry_writes_over_existing_in_default_mode(tmp_path: Path):
    (tmp_path / "fymo.yml").write_text("routes:\n  root: home.index\n")
    plan = [PlannedFile("fymo.yml", "routes:\n  root: home.index\n  posts: posts.index\n",
                        update=True)]
    written = execute_plan(tmp_path, plan, command="fymo generate page")
    assert written == ["fymo.yml"]
    assert "posts: posts.index" in (tmp_path / "fymo.yml").read_text()
