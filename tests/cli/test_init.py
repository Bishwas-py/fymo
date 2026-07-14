"""Tests for `fymo init` project initialization."""
from pathlib import Path

from fymo.cli.commands.init import initialize_project
from fymo.cli.commands.new import create_project


def test_init_scaffolds_fymo_yml_with_build_block(tmp_path: Path, monkeypatch):
    """`fymo init` used to omit the build: block that `fymo new` included --
    the two templates had silently drifted. Audit finding #6."""
    monkeypatch.chdir(tmp_path)
    initialize_project()
    content = (tmp_path / "fymo.yml").read_text()
    assert "routes:" in content
    assert "build:" in content


def test_init_and_new_scaffold_byte_identical_fymo_yml(tmp_path: Path, monkeypatch):
    """`fymo new <name>` and `fymo init` (run inside a directory named
    <name>) must produce byte-identical fymo.yml files for the same
    project name -- the two commands share one scaffold now."""
    new_root = tmp_path / "new_root"
    new_root.mkdir()
    monkeypatch.chdir(new_root)
    create_project("sample_app")
    new_fymo_yml = (new_root / "sample_app" / "fymo.yml").read_text()

    init_root = tmp_path / "sample_app"
    init_root.mkdir()
    monkeypatch.chdir(init_root)
    initialize_project()
    init_fymo_yml = (init_root / "fymo.yml").read_text()

    assert new_fymo_yml == init_fymo_yml
