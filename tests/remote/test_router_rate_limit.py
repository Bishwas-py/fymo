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
    "from fymo.remote import rate_limit\n"
    "@rate_limit(per_minute=2)\n"
    "def pricey() -> str: return 'paid'\n"
    "def cheap() -> str: return 'free'\n"
    "@rate_limit(per_minute=2, scope='uid')\n"
    "def per_uid() -> str: return 'uid-scoped'\n"
    "@rate_limit(per_minute=1, scope='user')\n"
    "def per_user() -> str: return 'user-scoped'\n"
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
