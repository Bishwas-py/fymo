"""Unit coverage for the shared SSR/soft-nav controller-invocation helper.

Fast, no Node sidecar, no example app -- just the scope-selection logic that
both the full-page renderer and the soft-nav data endpoint rely on to decide
whether to open a request scope around getContext()/getDoc().
"""
from contextlib import nullcontext

from fymo.core.ssr_controller import load_controller_context, ssr_request_scope


def test_scope_is_noop_when_auth_disabled():
    """auth_enabled=False must always yield a no-op context, regardless of environ."""
    scope = ssr_request_scope(False, {"HTTP_COOKIE": "fymo_session=whatever"})
    assert isinstance(scope, type(nullcontext()))


def test_scope_is_noop_when_environ_is_none():
    """No request environ (e.g. a direct render_template() call in a test) must
    also short-circuit to a no-op, even if auth is enabled."""
    scope = ssr_request_scope(True, None)
    assert isinstance(scope, type(nullcontext()))


def test_scope_is_real_when_auth_enabled_and_environ_present(monkeypatch):
    """When both auth is enabled and an environ is present, the real request
    scope (not nullcontext) must be opened."""
    from fymo.remote import identity

    monkeypatch.setattr(identity, "_secret", b"x" * 32)
    scope = ssr_request_scope(True, {"HTTP_COOKIE": ""})
    assert not isinstance(scope, type(nullcontext()))


def test_load_controller_context_calls_getcontext_and_getdoc():
    class FakeController:
        def getContext(self, id: str = ""):
            return {"id": id}

        def getDoc(self):
            return {"title": "Fake"}

    props, doc_meta = load_controller_context(
        FakeController(), {"id": "abc", "extra": "ignored"}, auth_enabled=False, environ=None
    )
    assert props == {"id": "abc"}
    assert doc_meta == {"title": "Fake"}


def test_load_controller_context_handles_missing_hooks():
    class EmptyController:
        pass

    props, doc_meta = load_controller_context(EmptyController(), {}, auth_enabled=False, environ=None)
    assert props == {}
    assert doc_meta == {}


def test_merge_docs_leaf_wins_on_scalar_keys():
    from fymo.core.ssr_controller import merge_docs
    merged = merge_docs([{"title": "Root default"}, {"title": "Post: Hello"}])
    assert merged["title"] == "Post: Hello"


def test_merge_docs_concatenates_head_meta_and_link():
    from fymo.core.ssr_controller import merge_docs
    root_doc = {"head": {"meta": [{"name": "og:site", "content": "Blog"}]}}
    leaf_doc = {"head": {"meta": [{"name": "description", "content": "A post"}], "link": [{"rel": "canonical", "href": "/x"}]}}
    merged = merge_docs([root_doc, leaf_doc])
    assert merged["head"]["meta"] == [
        {"name": "og:site", "content": "Blog"},
        {"name": "description", "content": "A post"},
    ]
    assert merged["head"]["link"] == [{"rel": "canonical", "href": "/x"}]


def test_merge_docs_empty_list_returns_empty_dict():
    from fymo.core.ssr_controller import merge_docs
    assert merge_docs([]) == {}


def test_load_layout_props_and_docs_fills_missing_levels_with_empty_dict(monkeypatch):
    from fymo.core.ssr_controller import load_layout_props_and_docs
    from fymo.build.manifest import LayoutRefAsset
    props_by_level, docs = load_layout_props_and_docs([], {}, False, None)
    assert props_by_level == {"root": {}, "resource": {}}
    assert docs == []


def test_load_layout_props_and_docs_invokes_controller_per_level(monkeypatch, tmp_path):
    import sys
    from fymo.core.ssr_controller import load_layout_props_and_docs
    from fymo.build.manifest import LayoutRefAsset

    pkg_dir = tmp_path / "layoutpkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "root_ctrl.py").write_text(
        "def getContext():\n    return {'nav_items': ['a', 'b']}\n"
        "def getDoc():\n    return {'title': 'Root'}\n"
    )
    (pkg_dir / "resource_ctrl.py").write_text(
        "def getContext():\n    return {'active_tab': 'posts'}\n"
        "def getDoc():\n    return {}\n"
    )
    sys.path.insert(0, str(tmp_path))
    try:
        chain = [
            LayoutRefAsset(level="root", id="_root", controller_module="layoutpkg.root_ctrl"),
            LayoutRefAsset(level="resource", id="posts", controller_module="layoutpkg.resource_ctrl"),
        ]
        props_by_level, docs = load_layout_props_and_docs(chain, {}, False, None)
        assert props_by_level["root"] == {"nav_items": ["a", "b"]}
        assert props_by_level["resource"] == {"active_tab": "posts"}
        assert docs == [{"title": "Root"}, {}]
    finally:
        sys.path.remove(str(tmp_path))
        for name in list(sys.modules):
            if name.startswith("layoutpkg"):
                del sys.modules[name]
