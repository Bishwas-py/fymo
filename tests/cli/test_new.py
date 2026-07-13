"""Tests for `fymo new` project scaffolding."""
from pathlib import Path
import json

from fymo.cli.commands.new import create_project


def test_scaffolds_app_lib_and_app_components_dirs(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    assert (tmp_path / "myapp" / "app" / "lib").is_dir()
    assert (tmp_path / "myapp" / "app" / "components").is_dir()


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
