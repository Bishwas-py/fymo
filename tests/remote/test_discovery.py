"""Discover app/remote/*.py modules and extract top-level callable signatures."""
import sys
from pathlib import Path
import pytest
from fymo.remote.discovery import discover_remote_modules, RemoteFunction


def _scaffold(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path


def test_discovers_top_level_functions(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": (
            "from typing import TypedDict\n"
            "class Post(TypedDict):\n"
            "    slug: str\n"
            "    title: str\n"
            "def get_post(slug: str) -> Post:\n"
            "    return {'slug': slug, 'title': 'x'}\n"
            "def _private(): return 1\n"  # underscore-prefixed = excluded
        ),
    })

    sys.path.insert(0, str(project))
    try:
        result = discover_remote_modules(project)
    finally:
        sys.path.remove(str(project))
        # Clean up imports so subsequent tests don't see this module
        for name in list(sys.modules):
            if name.startswith("app."):
                del sys.modules[name]

    assert "posts" in result
    assert "get_post" in result["posts"]
    assert "_private" not in result["posts"]
    fn = result["posts"]["get_post"]
    assert isinstance(fn, RemoteFunction)
    assert list(fn.signature.parameters.keys()) == ["slug"]
    assert fn.hints["slug"] is str


def test_returns_empty_when_no_remote_dir(tmp_path: Path):
    assert discover_remote_modules(tmp_path) == {}


def test_skips_private_modules(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/_helpers.py": "def util(): pass\n",  # _-prefixed module excluded
        "app/remote/public.py": "def hello() -> str: return 'hi'\n",
    })
    sys.path.insert(0, str(project))
    try:
        result = discover_remote_modules(project)
    finally:
        sys.path.remove(str(project))
        for name in list(sys.modules):
            if name.startswith("app."):
                del sys.modules[name]

    assert "public" in result
    assert "_helpers" not in result


def test_raises_on_untyped_parameter(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/bad.py": "def fn(x): return x\n",
    })
    sys.path.insert(0, str(project))
    try:
        with pytest.raises(ValueError, match="annotate"):
            discover_remote_modules(project)
    finally:
        sys.path.remove(str(project))
        for name in list(sys.modules):
            if name.startswith("app."):
                del sys.modules[name]
