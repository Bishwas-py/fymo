"""Request-scoped identity extras (issue #57).

Apps attach their own authorization-adjacent data (org, roles, scopes,
tenant) next to the resolved identity via register_identity_extras_hook(),
and read it back anywhere current_user() is readable via identity_extras().
fymo stores the value and never inspects it; absent means empty, never an
error.
"""
import base64
import io
import json
import sys
import threading
from pathlib import Path

import pytest

from fymo.auth import identity_extras, register_identity_extras_hook
from fymo.auth import context as auth_context
from fymo.auth.context import (
    current_user,
    register_session_resolver,
    require_auth,
    reset_identity_extras_hooks,
    reset_session_resolvers,
)
from fymo.auth.session import make_session_token
from fymo.auth.store import SqliteUserStore
from fymo.remote import devalue, router as router_mod
from fymo.remote.context import request_scope
from fymo.remote.identity import set_secret


@pytest.fixture
def store(tmp_path: Path):
    set_secret(b"x" * 32)
    s = SqliteUserStore(project_root=tmp_path)
    auth_context.set_user_store(s)
    yield s
    reset_session_resolvers()
    reset_identity_extras_hooks()


def _scope_with_session(user):
    token = make_session_token(user.id, user.session_epoch)
    return request_scope(uid="u_x", environ={"HTTP_COOKIE": f"fymo_session={token}"})


# --------------- unit: hook population + accessor ---------------


def test_hook_extras_readable_alongside_current_user(store):
    user = store.create("alice@example.com", "hash")
    register_identity_extras_hook(lambda u: {"org": "acme", "email": u.email})

    with _scope_with_session(user):
        assert current_user() is not None
        extras = identity_extras()
        assert extras["org"] == "acme"
        assert extras["email"] == "alice@example.com"


def test_hook_runs_once_per_request_scope(store):
    user = store.create("bob@example.com", "hash")
    calls = []
    register_identity_extras_hook(lambda u: calls.append(u.id) or {"n": len(calls)})

    with _scope_with_session(user):
        current_user()
        current_user()
        current_user()
        assert identity_extras()["n"] == 1
    assert calls == [user.id]


def test_absent_extras_returns_empty_mapping_inside_scope(store):
    user = store.create("carol@example.com", "hash")
    with _scope_with_session(user):
        # Before any resolution, and after resolution with no hooks
        # registered, extras read as empty.
        assert dict(identity_extras()) == {}
        assert current_user() is not None
        assert dict(identity_extras()) == {}


def test_anonymous_request_leaves_extras_empty(store):
    register_identity_extras_hook(lambda u: {"should": "never run"})
    with request_scope(uid="u_x", environ={}):
        assert current_user() is None
        assert dict(identity_extras()) == {}


def test_accessor_raises_outside_request_scope(store):
    with pytest.raises(RuntimeError, match="outside of a remote-function request scope"):
        identity_extras()


def test_hooks_merge_in_registration_order(store):
    user = store.create("dave@example.com", "hash")
    register_identity_extras_hook(lambda u: {"role": "viewer", "org": "acme"})
    register_identity_extras_hook(lambda u: {"role": "admin"})

    with _scope_with_session(user):
        current_user()
        extras = identity_extras()
        assert extras["role"] == "admin"
        assert extras["org"] == "acme"


def test_hook_runs_for_provider_resolved_identities(store):
    """The hook fires no matter which resolver in the chain resolved the
    user, so token/JWT provider identities get extras exactly like
    fymo-session ones."""
    user = store.create("token@example.com", "hash")
    register_session_resolver(
        lambda event: user
        if event.get("headers", {}).get("x-provider-token") == "ok"
        else None
    )
    register_identity_extras_hook(lambda u: {"via": "provider", "id": u.id})

    with request_scope(uid="u_x", environ={"HTTP_X_PROVIDER_TOKEN": "ok"}):
        assert current_user() is not None
        assert identity_extras()["via"] == "provider"
        assert identity_extras()["id"] == user.id


def test_extras_mapping_is_read_only(store):
    """The returned mapping is frozen: extras are populated once per scope,
    and nothing downstream may mutate them in place."""
    user = store.create("ro@example.com", "hash")
    register_identity_extras_hook(lambda u: {"org": "acme"})

    with _scope_with_session(user):
        empty = identity_extras()
        with pytest.raises(TypeError):
            empty["sneak"] = 1  # type: ignore[index]
        current_user()
        extras = identity_extras()
        with pytest.raises(TypeError):
            extras["org"] = "evil"  # type: ignore[index]


def test_registering_same_hook_twice_replaces_not_duplicates(store):
    def attach(user):
        return {"org": "acme"}

    register_identity_extras_hook(attach)
    register_identity_extras_hook(attach)
    assert len(auth_context._identity_extras_hooks) == 1


def test_hook_registration_survives_module_reload_without_duplicates(store, tmp_path, monkeypatch):
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
        "def attach(user):\n"
        "    CALLS.append(user.id)\n"
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

        user = store.create("reload@example.com", "hash")
        with _scope_with_session(user):
            current_user()
            assert dict(identity_extras()) == {"org": "acme"}
        assert mod.CALLS == [user.id]
    finally:
        sys.modules.pop(mod_name, None)


# --------------- concurrency: no leakage across scopes ---------------


def test_concurrent_scopes_do_not_leak_extras(store):
    alice = store.create("a@example.com", "hash")
    bob = store.create("b@example.com", "hash")
    register_identity_extras_hook(lambda u: {"email": u.email})

    barrier = threading.Barrier(2, timeout=10)
    results: dict[str, object] = {}
    errors: list[BaseException] = []

    def worker(name: str, user):
        try:
            with _scope_with_session(user):
                barrier.wait()  # both scopes open before either resolves
                current_user()
                barrier.wait()  # both populated before either reads
                results[name] = dict(identity_extras())
        except BaseException as e:  # noqa: BLE001 - surface thread failures
            errors.append(e)

    threads = [
        threading.Thread(target=worker, args=("alice", alice)),
        threading.Thread(target=worker, args=("bob", bob)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, errors
    assert results["alice"] == {"email": "a@example.com"}
    assert results["bob"] == {"email": "b@example.com"}


# --------------- acceptance: full remote-router round trip ---------------


@pytest.fixture(autouse=True)
def _wire_secret():
    set_secret(b"x" * 32)


@pytest.fixture
def app_env(tmp_path: Path, monkeypatch):
    """Same wiring as tests/auth/test_remote_e2e.py: password provider's
    remote functions dispatched through the real router, plus an app-authored
    function that reads identity_extras()."""
    from fymo.auth.providers.password import PasswordProvider
    from fymo.auth.providers.registry import system_remote_modules
    from fymo.remote.discovery import _functions_hash

    store = SqliteUserStore(project_root=tmp_path)
    auth_context.set_user_store(store)

    @require_auth
    def my_extras() -> dict:
        return dict(identity_extras())

    modules = system_remote_modules([PasswordProvider()])
    modules["auth"]["my_extras"] = my_extras
    router_mod.set_system_modules(modules)
    auth_hash = _functions_hash(modules["auth"])

    monkeypatch.setattr(
        router_mod,
        "_resolve_module_for_hash",
        lambda h: "auth" if h == auth_hash else None,
    )
    yield store, auth_hash
    router_mod.set_system_modules({})
    reset_session_resolvers()
    reset_identity_extras_hooks()


def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).rstrip(b"=").decode("ascii")


def _call(hash_: str, fn: str, args: list, cookies: str = ""):
    body = json.dumps({"payload": _b64url(devalue.stringify(args))}).encode()
    env = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": f"/_fymo/remote/{hash_}/{fn}",
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": "application/json",
        "HTTP_COOKIE": cookies,
        "HTTP_HOST": "x",
        "HTTP_ORIGIN": "http://x",
        "wsgi.url_scheme": "http",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(body),
        "wsgi.errors": sys.stderr,
    }
    responses = []
    def sr(status, headers): responses.append((status, headers))
    out = b"".join(router_mod.handle_remote(env, sr))
    return responses[0], json.loads(out)


def _extract_cookie(headers, name) -> str | None:
    for k, v in headers:
        if k.lower() == "set-cookie" and v.startswith(f"{name}="):
            return v.split(";", 1)[0]
    return None


def test_extras_attached_at_resolution_read_back_in_remote_function(app_env):
    """Acceptance (issue #57): an app attaches a dict of its own data when
    the session resolves and reads it back from inside a remote function via
    the public accessor, without touching fymo's User shape."""
    _, h = app_env
    register_identity_extras_hook(
        lambda user: {"org": "acme", "roles": ["admin"], "owner_of": [user.id]}
    )

    (_, headers), env = _call(h, "signup", ["alice@example.com", "longpassword"])
    session_cookie = _extract_cookie(headers, "fymo_session")
    user = devalue.parse(env["result"])

    (_, _), env = _call(h, "my_extras", [], cookies=session_cookie)
    assert env["type"] == "result", env
    extras = devalue.parse(env["result"])
    assert extras == {"org": "acme", "roles": ["admin"], "owner_of": [user["id"]]}


def test_remote_function_sees_empty_extras_when_nothing_attached(app_env):
    """Absent means empty, never an error: no hook registered, the accessor
    still answers with an empty mapping through the full router path."""
    _, h = app_env
    (_, headers), _ = _call(h, "signup", ["bob@example.com", "longpassword"])
    session_cookie = _extract_cookie(headers, "fymo_session")

    (_, _), env = _call(h, "my_extras", [], cookies=session_cookie)
    assert env["type"] == "result", env
    assert devalue.parse(env["result"]) == {}
