"""Tests for fymo.core.app_discovery — the generic app/<pkg>/*.py top-level
function walker shared by fymo.jobs.discovery and fymo.broadcast.discovery."""
import sys
from pathlib import Path

import pytest

from fymo.core.app_discovery import discover_app_functions


class _DupError(Exception):
    pass


def _on_duplicate(name: str, first: str, second: str) -> _DupError:
    return _DupError(f"{name!r} in both {first} and {second}")


def _write_module(tmp_path: Path, subpackage: str, module: str, source: str) -> Path:
    pkg_dir = tmp_path / "app" / subpackage
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "app" / "__init__.py").touch()
    (pkg_dir / "__init__.py").touch()
    (pkg_dir / f"{module}.py").write_text(source)
    return tmp_path


def test_returns_empty_dict_when_dir_missing(tmp_path: Path):
    assert discover_app_functions(tmp_path, "widgets", _on_duplicate) == {}


def test_discovers_top_level_functions(tmp_path: Path):
    _write_module(tmp_path, "widgets", "mod", "def visible(x):\n    return x\n")
    found = discover_app_functions(tmp_path, "widgets", _on_duplicate)
    assert set(found) == {"visible"}
    module, fn = found["visible"]
    assert module == "mod"
    assert fn(1) == 1


def test_skips_private_functions_and_modules(tmp_path: Path):
    _write_module(tmp_path, "widgets", "mod", "def _hidden():\n    ...\n\ndef visible():\n    ...\n")
    _write_module(tmp_path, "widgets", "_private", "def also_hidden():\n    ...\n")
    found = discover_app_functions(tmp_path, "widgets", _on_duplicate)
    assert set(found) == {"visible"}


def test_skips_imported_not_defined_functions(tmp_path: Path):
    _write_module(tmp_path, "widgets", "helper", "def helper_fn():\n    ...\n")
    _write_module(tmp_path, "widgets", "mod", "from app.widgets.helper import helper_fn\n")
    found = discover_app_functions(tmp_path, "widgets", _on_duplicate)
    # helper_fn is defined in helper.py and merely re-imported (not
    # redefined) in mod.py -- discovery should attribute it to helper only.
    assert set(found) == {"helper_fn"}
    module, _fn = found["helper_fn"]
    assert module == "helper"


def test_duplicate_names_raise_via_on_duplicate(tmp_path: Path):
    _write_module(tmp_path, "widgets", "a", "def clash():\n    ...\n")
    _write_module(tmp_path, "widgets", "b", "def clash():\n    ...\n")
    with pytest.raises(_DupError, match="clash"):
        discover_app_functions(tmp_path, "widgets", _on_duplicate)


def test_sys_path_restored_after(tmp_path: Path):
    _write_module(tmp_path, "widgets", "mod", "def visible():\n    ...\n")
    before = list(sys.path)
    discover_app_functions(tmp_path, "widgets", _on_duplicate)
    assert sys.path == before
