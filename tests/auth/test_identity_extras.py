"""Request-scoped identity extras: the hook machinery (issue #57, retargeted
to the uid chain by issue #80).

Apps attach their own authorization-adjacent data (org, roles, scopes,
tenant) next to the resolved identity via register_identity_extras_hook(),
and read it back anywhere current_uid() is readable via identity_extras().
Hooks receive the resolved uid string; fymo stores the merged value and
never inspects it; absent means empty, never an error.

The population-path tests (hook fires with the resolved uid, once per
scope, never for anonymous, seeded-resolution path) live in
tests/auth/test_identity_uid_extras.py; this file pins the machinery
around them: merge order, registration dedup, immutability, isolation
across concurrent scopes.
"""
import sys
import threading

import pytest

from fymo.auth import (
    Identity,
    identify,
    identity_extras,
    register_identity_extras_hook,
)
from fymo.auth import context as auth_context
from fymo.auth.context import reset_identity_extras_hooks
from fymo.auth.identity import current_uid, reset_identity_resolvers
from fymo.remote.context import request_scope
from fymo.remote.identity import set_secret


@pytest.fixture(autouse=True)
def _clean():
    set_secret(b"x" * 32)
    reset_identity_resolvers()
    reset_identity_extras_hooks()
    yield
    reset_identity_resolvers()
    reset_identity_extras_hooks()


def _resolve_header_uid():
    @identify
    def by_header(event):
        uid = event.headers.get("x-user")
        return Identity(uid=uid) if uid else None


def _scope(uid: "str | None" = "u_alice"):
    environ = {"HTTP_X_USER": uid} if uid else {}
    return request_scope(uid="u_anon", environ=environ)


def test_accessor_raises_outside_request_scope():
    with pytest.raises(RuntimeError, match="outside of a remote-function request scope"):
        identity_extras()


def test_hooks_merge_in_registration_order():
    _resolve_header_uid()
    register_identity_extras_hook(lambda uid: {"role": "viewer", "org": "acme"})
    register_identity_extras_hook(lambda uid: {"role": "admin"})

    with _scope():
        current_uid()
        extras = identity_extras()
        assert extras["role"] == "admin"
        assert extras["org"] == "acme"


def test_extras_mapping_is_read_only():
    """The returned mapping is frozen: extras are populated once per scope,
    and nothing downstream may mutate them in place."""
    _resolve_header_uid()
    register_identity_extras_hook(lambda uid: {"org": "acme"})

    with _scope():
        empty = identity_extras()
        with pytest.raises(TypeError):
            empty["sneak"] = 1  # type: ignore[index]
        current_uid()
        extras = identity_extras()
        with pytest.raises(TypeError):
            extras["org"] = "evil"  # type: ignore[index]


def test_registering_same_hook_twice_replaces_not_duplicates():
    def attach(uid):
        return {"org": "acme"}

    register_identity_extras_hook(attach)
    register_identity_extras_hook(attach)
    assert len(auth_context._identity_extras_hooks) == 1


def test_hook_registration_survives_module_reload_without_duplicates(tmp_path, monkeypatch):
    """The dev process re-executes app module bodies several times per
    reload (hygiene check, guarded-sites scan, discovery, each via
    importlib.reload), and reload creates a new function object every pass.
    A top-level register_identity_extras_hook call must replace its stale
    predecessor, not accumulate one copy per pass."""
    import importlib

    mod_name = "fymo_issue57_hookmod"
    (tmp_path / f"{mod_name}.py").write_text(
        "from fymo.auth import register_identity_extras_hook\n"
        "\n"
        "CALLS = []\n"
        "\n"
        "def attach(uid):\n"
        "    CALLS.append(uid)\n"
        "    return {'org': 'acme'}\n"
        "\n"
        "register_identity_extras_hook(attach)\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    mod = importlib.import_module(mod_name)
    try:
        mod = importlib.reload(mod)
        mod = importlib.reload(mod)

        assert len(auth_context._identity_extras_hooks) == 1
        assert auth_context._identity_extras_hooks[0] is mod.attach

        _resolve_header_uid()
        with _scope("u_reload"):
            current_uid()
            assert dict(identity_extras()) == {"org": "acme"}
        assert mod.CALLS == ["u_reload"]
    finally:
        sys.modules.pop(mod_name, None)


def test_concurrent_scopes_do_not_leak_extras():
    _resolve_header_uid()
    register_identity_extras_hook(lambda uid: {"who": uid})

    barrier = threading.Barrier(2, timeout=10)
    results: dict[str, object] = {}
    errors: list[BaseException] = []

    def worker(uid: str):
        try:
            with _scope(uid):
                barrier.wait()  # both scopes open before either resolves
                current_uid()
                barrier.wait()  # both populated before either reads
                results[uid] = dict(identity_extras())
        except BaseException as e:  # noqa: BLE001 - surface thread failures
            errors.append(e)

    threads = [
        threading.Thread(target=worker, args=("u_alice",)),
        threading.Thread(target=worker, args=("u_bob",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, errors
    assert results["u_alice"] == {"who": "u_alice"}
    assert results["u_bob"] == {"who": "u_bob"}
