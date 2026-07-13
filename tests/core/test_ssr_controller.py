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
