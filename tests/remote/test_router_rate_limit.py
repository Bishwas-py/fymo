"""Router enforcement of @rate_limit: per-(function, scope-key) budgets
checked at dispatch time, before the function runs.

Over-limit responses use the standard envelope over HTTP 200, matching
every other RemoteError the router serializes.
"""
import base64
import io
import json
import sys

import pytest

from fymo.remote import devalue
from fymo.remote import router as router_mod
from fymo.remote.identity import _sign
from fymo.remote.rate_limit import reset_rate_limit_state


MODULE_SRC = (
    "from fymo.auth import current_uid\n"
    "from fymo.remote import rate_limit\n"
    "@rate_limit(per_minute=2)\n"
    "def pricey() -> str: return 'paid'\n"
    "def cheap() -> str: return 'free'\n"
    "@rate_limit(per_minute=2, scope='uid')\n"
    "def per_uid() -> str: return 'uid-scoped'\n"
    "@rate_limit(per_minute=1, scope='user')\n"
    "def per_user() -> str: return 'user-scoped'\n"
    "@rate_limit(per_minute=5, scope='user')\n"
    "def whoami() -> str: return current_uid() or 'anon'\n"
)


def _scaffold(tmp_path, files):
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path


def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).rstrip(b"=").decode("ascii")


def _make_environ(path: str, args: list, *, cookies: str = "", ip: str = "127.0.0.1",
                  xff: str | None = None):
    body_obj = {"payload": _b64url(devalue.stringify(args))}
    raw = json.dumps(body_obj).encode()
    env = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(raw)),
        "CONTENT_TYPE": "application/json",
        "HTTP_COOKIE": cookies,
        "HTTP_HOST": "x",
        "HTTP_ORIGIN": "http://x",
        "wsgi.url_scheme": "http",
        "REMOTE_ADDR": ip,
        "wsgi.input": io.BytesIO(raw),
    }
    if xff is not None:
        env["HTTP_X_FORWARDED_FOR"] = xff
    return env


def _call(environ):
    responses = []
    def sr(status, headers): responses.append((status, headers))
    body = b"".join(router_mod.handle_remote(environ, sr))
    return responses[0], json.loads(body)


@pytest.fixture(autouse=True)
def _fresh_buckets():
    reset_rate_limit_state()
    yield
    reset_rate_limit_state()


@pytest.fixture
def limited_project(tmp_path, monkeypatch):
    proj = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/billing.py": MODULE_SRC,
    })
    monkeypatch.syspath_prepend(str(proj))

    from fymo.remote.discovery import file_hash
    h = file_hash(proj / "app/remote/billing.py")
    monkeypatch.setattr(
        router_mod, "_resolve_module_for_hash",
        lambda hash_: "billing" if hash_ == h else None,
    )

    yield proj, h
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


def _uid_cookie(uid: str) -> str:
    return f"fymo_uid={uid}.{_sign(uid)}"


# ---------------- ip scope ----------------


def test_under_limit_passes(limited_project):
    _, h = limited_project
    for _ in range(2):
        (status, _), body = _call(_make_environ(f"/_fymo/remote/{h}/pricey", []))
        assert status.startswith("200")
        assert body["type"] == "result"
        assert devalue.parse(body["result"]) == "paid"


def test_over_limit_returns_429_envelope_over_http_200(limited_project):
    _, h = limited_project
    _call(_make_environ(f"/_fymo/remote/{h}/pricey", []))
    _call(_make_environ(f"/_fymo/remote/{h}/pricey", []))
    (status, _), body = _call(_make_environ(f"/_fymo/remote/{h}/pricey", []))
    assert status.startswith("200")
    assert body["type"] == "error"
    assert body["status"] == 429
    assert body["error"] == "rate_limited"
    assert body["retry_after"] >= 1


def test_other_functions_in_module_unaffected(limited_project):
    _, h = limited_project
    for _ in range(3):
        _call(_make_environ(f"/_fymo/remote/{h}/pricey", []))
    (_, _), body = _call(_make_environ(f"/_fymo/remote/{h}/cheap", []))
    assert body["type"] == "result"
    assert devalue.parse(body["result"]) == "free"


def test_separate_ips_get_separate_buckets(limited_project):
    _, h = limited_project
    for _ in range(2):
        _call(_make_environ(f"/_fymo/remote/{h}/pricey", [], ip="1.1.1.1"))
    (_, _), blocked = _call(_make_environ(f"/_fymo/remote/{h}/pricey", [], ip="1.1.1.1"))
    assert blocked["status"] == 429
    (_, _), other = _call(_make_environ(f"/_fymo/remote/{h}/pricey", [], ip="2.2.2.2"))
    assert other["type"] == "result"


def test_ip_scope_honors_trust_proxy_xff(limited_project, monkeypatch):
    """Same trust boundary as the middleware limiter: the forwarded hop only
    counts when the app was configured with trust_proxy on."""
    _, h = limited_project
    from fymo.remote import context as context_mod
    monkeypatch.setattr(context_mod, "_trust_proxy", True)
    for _ in range(2):
        _call(_make_environ(f"/_fymo/remote/{h}/pricey", [], ip="10.0.0.1", xff="9.9.9.9"))
    (_, _), blocked = _call(_make_environ(f"/_fymo/remote/{h}/pricey", [], ip="10.0.0.1", xff="9.9.9.9"))
    assert blocked["status"] == 429
    # A different forwarded client behind the same proxy gets a fresh bucket.
    (_, _), other = _call(_make_environ(f"/_fymo/remote/{h}/pricey", [], ip="10.0.0.1", xff="8.8.8.8"))
    assert other["type"] == "result"


def test_ip_scope_ignores_xff_without_trust_proxy(limited_project):
    _, h = limited_project
    for _ in range(2):
        _call(_make_environ(f"/_fymo/remote/{h}/pricey", [], ip="10.0.0.1", xff="9.9.9.9"))
    (_, _), blocked = _call(_make_environ(f"/_fymo/remote/{h}/pricey", [], ip="10.0.0.1", xff="SPOOFED"))
    assert blocked["status"] == 429


def test_function_never_runs_when_over_limit(limited_project, tmp_path):
    """Enforcement happens before dispatch: a limited call must not produce
    the function's side effects."""
    proj, _ = limited_project
    marker = tmp_path / "calls.txt"
    src = (
        "from fymo.remote import rate_limit\n"
        f"MARKER = {str(marker)!r}\n"
        "@rate_limit(per_minute=1)\n"
        "def tracked() -> str:\n"
        "    with open(MARKER, 'a') as f: f.write('x')\n"
        "    return 'ok'\n"
    )
    (proj / "app/remote/billing.py").write_text(src)
    from fymo.remote.discovery import file_hash
    new_h = file_hash(proj / "app/remote/billing.py")
    import fymo.remote.router as rm
    old_resolver = rm._resolve_module_for_hash
    rm._resolve_module_for_hash = lambda hash_: "billing" if hash_ == new_h else None
    try:
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        _call(_make_environ(f"/_fymo/remote/{new_h}/tracked", []))
        (_, _), body = _call(_make_environ(f"/_fymo/remote/{new_h}/tracked", []))
        assert body["status"] == 429
        assert marker.read_text() == "x"
    finally:
        rm._resolve_module_for_hash = old_resolver


# ---------------- uid scope ----------------


def test_uid_scope_separate_cookies_get_separate_buckets(limited_project):
    _, h = limited_project
    alice, bob = _uid_cookie("u_alice"), _uid_cookie("u_bob")
    for _ in range(2):
        _call(_make_environ(f"/_fymo/remote/{h}/per_uid", [], cookies=alice))
    (_, _), blocked = _call(_make_environ(f"/_fymo/remote/{h}/per_uid", [], cookies=alice))
    assert blocked["status"] == 429
    # Same IP, different uid: fresh bucket.
    (_, _), other = _call(_make_environ(f"/_fymo/remote/{h}/per_uid", [], cookies=bob))
    assert other["type"] == "result"


def test_uid_scope_falls_back_to_ip_without_cookie(limited_project):
    """A cookieless retry loop would get a fresh uid per request, so the
    limit must bind on IP instead of silently not applying."""
    _, h = limited_project
    for _ in range(2):
        _call(_make_environ(f"/_fymo/remote/{h}/per_uid", []))
    (_, _), blocked = _call(_make_environ(f"/_fymo/remote/{h}/per_uid", []))
    assert blocked["status"] == 429


def test_uid_scope_ignores_forged_cookie(limited_project):
    """A cookie that fails HMAC verification must not mint fresh buckets."""
    _, h = limited_project
    for i in range(2):
        _call(_make_environ(
            f"/_fymo/remote/{h}/per_uid", [],
            cookies=f"fymo_uid=u_forged{i}.AAAAAAAAAAAAAAAAAAAAAA",
        ))
    (_, _), blocked = _call(_make_environ(
        f"/_fymo/remote/{h}/per_uid", [],
        cookies="fymo_uid=u_forged9.AAAAAAAAAAAAAAAAAAAAAA",
    ))
    assert blocked["status"] == 429


# ---------------- user scope ----------------


@pytest.fixture
def user_store(tmp_path, monkeypatch):
    from fymo.auth import context as auth_context
    from fymo.auth.store import SqliteUserStore
    store = SqliteUserStore(project_root=tmp_path)
    monkeypatch.setattr(auth_context, "_user_store", store)
    yield store


def _session_cookie(user) -> str:
    from fymo.auth.session import make_session_token
    return f"fymo_session={make_session_token(user.id, user.session_epoch)}"


def test_user_scope_keys_on_authenticated_user(limited_project, user_store):
    _, h = limited_project
    alice = user_store.create("alice@x.com", None)
    bob = user_store.create("bob@x.com", None)

    (_, _), first = _call(_make_environ(
        f"/_fymo/remote/{h}/per_user", [], cookies=_session_cookie(alice)))
    assert first["type"] == "result"
    (_, _), blocked = _call(_make_environ(
        f"/_fymo/remote/{h}/per_user", [], cookies=_session_cookie(alice)))
    assert blocked["status"] == 429
    # Same IP, different signed-in user: fresh bucket.
    (_, _), other = _call(_make_environ(
        f"/_fymo/remote/{h}/per_user", [], cookies=_session_cookie(bob)))
    assert other["type"] == "result"


def test_user_scope_falls_back_to_uid_when_unauthenticated(limited_project, user_store):
    _, h = limited_project
    alice, bob = _uid_cookie("u_anon1"), _uid_cookie("u_anon2")
    (_, _), first = _call(_make_environ(f"/_fymo/remote/{h}/per_user", [], cookies=alice))
    assert first["type"] == "result"
    (_, _), blocked = _call(_make_environ(f"/_fymo/remote/{h}/per_user", [], cookies=alice))
    assert blocked["status"] == 429
    (_, _), other = _call(_make_environ(f"/_fymo/remote/{h}/per_user", [], cookies=bob))
    assert other["type"] == "result"


def test_user_scope_falls_back_to_ip_with_no_identity_at_all(limited_project):
    """No session, no uid cookie, and no user store configured: the limit
    still binds on IP rather than silently not applying."""
    _, h = limited_project
    (_, _), first = _call(_make_environ(f"/_fymo/remote/{h}/per_user", []))
    assert first["type"] == "result"
    (_, _), blocked = _call(_make_environ(f"/_fymo/remote/{h}/per_user", []))
    assert blocked["status"] == 429


# ---------------- user scope: @identify chain (issue #80) ----------------


@pytest.fixture
def identity_chain():
    from fymo.auth.identity import reset_identity_resolvers
    reset_identity_resolvers()
    yield
    reset_identity_resolvers()


def _keyed_environ(h: str, fn: str, api_key: "str | None" = None, cookies: str = ""):
    env = _make_environ(f"/_fymo/remote/{h}/{fn}", [], cookies=cookies)
    if api_key is not None:
        env["HTTP_X_API_KEY"] = api_key
    return env


def test_user_scope_keys_on_identify_resolver(limited_project, identity_chain):
    from fymo.auth import Identity, identify

    @identify
    def by_api_key(event):
        key = event.headers.get("x-api-key")
        return Identity(uid=f"key_{key}") if key else None

    _, h = limited_project
    (_, _), first = _call(_keyed_environ(h, "per_user", api_key="alpha"))
    assert first["type"] == "result"
    (_, _), blocked = _call(_keyed_environ(h, "per_user", api_key="alpha"))
    assert blocked["status"] == 429
    # Same IP, different resolved identity: fresh bucket.
    (_, _), other = _call(_keyed_environ(h, "per_user", api_key="beta"))
    assert other["type"] == "result"


def test_identify_resolver_wins_over_legacy_session(limited_project, user_store, identity_chain):
    """New chain first: when an @identify resolver matches, its uid is the
    key even for a request whose legacy fymo_session would also resolve."""
    from fymo.auth import Identity, identify

    @identify
    def everyone_shares_one_identity(event):
        return Identity(uid="shared")

    _, h = limited_project
    alice = user_store.create("alice@x.com", None)
    bob = user_store.create("bob@x.com", None)
    (_, _), first = _call(_make_environ(
        f"/_fymo/remote/{h}/per_user", [], cookies=_session_cookie(alice)))
    assert first["type"] == "result"
    # Under the legacy chain bob would get his own bucket; the identify
    # chain wins, so bob lands in alice's "user:shared" bucket.
    (_, _), blocked = _call(_make_environ(
        f"/_fymo/remote/{h}/per_user", [], cookies=_session_cookie(bob)))
    assert blocked["status"] == 429


def test_legacy_session_still_keys_when_no_resolver_matches(limited_project, user_store, identity_chain):
    """Coexistence: with a resolver registered but not matching, the legacy
    session walk still keys signed-in users individually."""
    from fymo.auth import identify

    @identify
    def never_matches(event):
        return None

    _, h = limited_project
    alice = user_store.create("alice@x.com", None)
    bob = user_store.create("bob@x.com", None)
    (_, _), first = _call(_make_environ(
        f"/_fymo/remote/{h}/per_user", [], cookies=_session_cookie(alice)))
    assert first["type"] == "result"
    (_, _), blocked = _call(_make_environ(
        f"/_fymo/remote/{h}/per_user", [], cookies=_session_cookie(alice)))
    assert blocked["status"] == 429
    (_, _), other = _call(_make_environ(
        f"/_fymo/remote/{h}/per_user", [], cookies=_session_cookie(bob)))
    assert other["type"] == "result"


def test_stale_session_no_resolvers_no_store_falls_back_to_uid(limited_project, identity_chain, monkeypatch):
    """The acceptance criterion: a well-formed fymo_session cookie on an app
    with zero identify resolvers and no UserStore configured must not crash,
    must not touch any store, and must key on the verified fymo_uid (then
    IP) exactly as before."""
    from fymo.auth import context as auth_context
    from fymo.auth.session import make_session_token
    monkeypatch.setattr(auth_context, "_user_store", None)
    session = f"fymo_session={make_session_token(1, 0)}"

    _, h = limited_project
    a = f"{session}; {_uid_cookie('u_anon1')}"
    b = f"{session}; {_uid_cookie('u_anon2')}"
    (_, _), first = _call(_make_environ(f"/_fymo/remote/{h}/per_user", [], cookies=a))
    assert first["type"] == "result"
    (_, _), blocked = _call(_make_environ(f"/_fymo/remote/{h}/per_user", [], cookies=a))
    assert blocked["status"] == 429
    (_, _), other = _call(_make_environ(f"/_fymo/remote/{h}/per_user", [], cookies=b))
    assert other["type"] == "result"
    # No uid cookie either: binds on IP rather than crashing or not applying.
    (_, _), ip_first = _call(_make_environ(
        f"/_fymo/remote/{h}/per_user", [], cookies=session, ip="3.3.3.3"))
    assert ip_first["type"] == "result"
    (_, _), ip_blocked = _call(_make_environ(
        f"/_fymo/remote/{h}/per_user", [], cookies=session, ip="3.3.3.3"))
    assert ip_blocked["status"] == 429


def test_user_scope_raising_resolver_fails_open_to_next_tier(limited_project, identity_chain):
    """Fail-open: a resolver crashing during key resolution must not take
    the request down; the key degrades to the fymo_uid tier instead."""
    from fymo.auth import identify

    @identify
    def broken(event):
        raise RuntimeError("resolver exploded")

    _, h = limited_project
    a, b = _uid_cookie("u_x1"), _uid_cookie("u_x2")
    (_, _), first = _call(_make_environ(f"/_fymo/remote/{h}/per_user", [], cookies=a))
    assert first["type"] == "result"
    (_, _), blocked = _call(_make_environ(f"/_fymo/remote/{h}/per_user", [], cookies=a))
    assert blocked["status"] == 429
    (_, _), other = _call(_make_environ(f"/_fymo/remote/{h}/per_user", [], cookies=b))
    assert other["type"] == "result"


def test_user_scope_raising_resolver_does_not_shadow_later_resolver(limited_project, identity_chain):
    from fymo.auth import Identity, identify

    @identify
    def broken(event):
        raise RuntimeError("resolver exploded")

    @identify
    def by_api_key(event):
        key = event.headers.get("x-api-key")
        return Identity(uid=f"key_{key}") if key else None

    _, h = limited_project
    (_, _), first = _call(_keyed_environ(h, "per_user", api_key="alpha"))
    assert first["type"] == "result"
    (_, _), blocked = _call(_keyed_environ(h, "per_user", api_key="alpha"))
    assert blocked["status"] == 429
    (_, _), other = _call(_keyed_environ(h, "per_user", api_key="beta"))
    assert other["type"] == "result"


def test_identify_chain_runs_once_per_request_shared_with_current_uid(limited_project, identity_chain):
    """Rate-limit key resolution shares current_uid()'s per-request cache:
    the handler's own current_uid() call must not re-run the chain."""
    from fymo.auth import Identity, identify

    calls = []

    @identify
    def counting(event):
        calls.append(1)
        return Identity(uid="u_counted")

    _, h = limited_project
    (_, _), body = _call(_make_environ(f"/_fymo/remote/{h}/whoami", []))
    assert body["type"] == "result"
    assert devalue.parse(body["result"]) == "u_counted"
    assert len(calls) == 1


def test_unclean_walk_is_not_cached_handler_stays_fail_loud(limited_project, identity_chain):
    """Fail-open covers only the rate-limit key. A walk that swallowed a
    resolver exception is not cached, so current_uid() inside the handler
    re-runs the chain and keeps its fail-loud contract (500 envelope)."""
    from fymo.auth import identify

    @identify
    def broken(event):
        raise RuntimeError("resolver exploded")

    _, h = limited_project
    (status, _), body = _call(_make_environ(f"/_fymo/remote/{h}/whoami", []))
    assert status.startswith("200")
    assert body["type"] == "error"
    assert body["status"] == 500
    assert body["error"] == "internal"


def test_user_scope_garbage_resolver_does_not_shadow_later_resolver(limited_project, identity_chain):
    from fymo.auth import Identity, identify

    @identify
    def garbage(event):
        return "not-an-identity"

    @identify
    def by_api_key(event):
        key = event.headers.get("x-api-key")
        return Identity(uid=f"key_{key}") if key else None

    _, h = limited_project
    (_, _), first = _call(_keyed_environ(h, "per_user", api_key="alpha"))
    assert first["type"] == "result"
    (_, _), blocked = _call(_keyed_environ(h, "per_user", api_key="alpha"))
    assert blocked["status"] == 429
    (_, _), other = _call(_keyed_environ(h, "per_user", api_key="beta"))
    assert other["type"] == "result"


def test_garbage_return_walk_is_not_cached_handler_stays_fail_loud(limited_project, identity_chain):
    """The other unclean half: a resolver returning a non-Identity value is
    skipped for the rate-limit key and the walk is not cached, so the
    handler's current_uid() re-runs the chain and raises the resolver
    return-type error (500 envelope). Caching the walk would hand the
    handler a silent None instead."""
    from fymo.auth import identify

    @identify
    def garbage(event):
        return "not-an-identity"

    _, h = limited_project
    (status, _), body = _call(_make_environ(f"/_fymo/remote/{h}/whoami", []))
    assert status.startswith("200")
    assert body["type"] == "error"
    assert body["status"] == 500
    assert body["error"] == "internal"


# ---------------- RateLimited raised from app code ----------------


def test_app_raised_rate_limited_surfaces_retry_after(limited_project):
    proj, _ = limited_project
    src = (
        "from fymo.remote import RateLimited\n"
        "def manual() -> str: raise RateLimited('slow down', retry_after=7)\n"
    )
    (proj / "app/remote/billing.py").write_text(src)
    from fymo.remote.discovery import file_hash
    new_h = file_hash(proj / "app/remote/billing.py")
    import fymo.remote.router as rm
    old_resolver = rm._resolve_module_for_hash
    rm._resolve_module_for_hash = lambda hash_: "billing" if hash_ == new_h else None
    try:
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        (status, _), body = _call(_make_environ(f"/_fymo/remote/{new_h}/manual", []))
        assert status.startswith("200")
        assert body["status"] == 429
        assert body["error"] == "rate_limited"
        assert body["retry_after"] == 7
    finally:
        rm._resolve_module_for_hash = old_resolver
