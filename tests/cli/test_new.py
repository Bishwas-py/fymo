"""Tests for `fymo new` project scaffolding."""
from pathlib import Path
import json

from fymo.cli.commands.new import create_project


def test_scaffolds_app_lib_and_app_lib_server_dirs(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    assert (tmp_path / "myapp" / "app" / "lib").is_dir()
    assert (tmp_path / "myapp" / "app" / "lib" / "server").is_dir()


def test_scaffolds_tsconfig_with_lib_shared_and_remote_aliases(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_project("myapp")
    tsconfig_path = tmp_path / "myapp" / "tsconfig.json"
    assert tsconfig_path.is_file()
    data = json.loads(tsconfig_path.read_text())
    paths = data["compilerOptions"]["paths"]
    assert paths["$lib/*"] == ["./app/lib/*"]
    assert paths["$_shared/*"] == ["./app/templates/_shared/*"]
    assert paths["$remote/*"] == ["./dist/client/_remote/*"]
    # app/lib/server/* is deliberately NOT an importable alias -- it's
    # guarded at build time instead (server-only-guard.mjs), not resolved
    # via a client-facing alias.
    assert not any("server" in key for key in paths)
