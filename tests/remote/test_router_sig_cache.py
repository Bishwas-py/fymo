"""Signature/type-hint reflection caching in _resolve_fn_in_module.

typing.get_type_hints() resolves annotations against module globals and
builds a dict on every call; inspect.signature() walks parameters, both do
real work that produces the same result every time for an unchanged
function object. These tests pin down that the router memoizes that work
per (module, fn_name) and correctly evicts the cache when the underlying
function object changes (e.g. a provider re-registering a new version of a
function under the same name, the system-module equivalent of a hot-reload).

Exercised via the `_system_modules` allowlist path (the framework-shipped
module route in _resolve_fn_in_module) rather than app/remote/*.py, because
that path hands back the exact same function object across requests with no
import machinery involved, an isolated, deterministic way to prove the
memoization itself, independent of anything import-related.
"""
import io
import base64
import json
import typing as typing_mod
import pytest
from fymo.remote.router import handle_remote
from fymo.remote import router as router_mod
from fymo.remote import devalue


def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).rstrip(b"=").decode("ascii")


def _make_environ(path: str, args: list, *, host: str = "x", origin: "str | None" = "http://x"):
    body_obj = {"payload": _b64url(devalue.stringify(args))}
    raw = json.dumps(body_obj).encode()
    env = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(raw)),
        "CONTENT_TYPE": "application/json",
        "HTTP_COOKIE": "",
        "HTTP_HOST": host,
        "wsgi.url_scheme": "http",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(raw),
    }
    if origin is not None:
        env["HTTP_ORIGIN"] = origin
    return env


def _call(environ):
    responses = []
    def sr(status, headers): responses.append((status, headers))
    body = b"".join(handle_remote(environ, sr))
    return responses[0], json.loads(body)


@pytest.fixture
def system_module(monkeypatch):
    """Registers a single system-module function ('sysmod.hello') and clears
    the router's signature cache before and after so tests don't leak state
    into each other through the shared module-level dict."""
    def hello(name: str) -> str:
        return f"hi {name}"

    monkeypatch.setattr(router_mod, "_resolve_module_for_hash", lambda h: "sysmod" if h == "deadbeef0000" else None)
    monkeypatch.setattr(router_mod, "_system_modules", {"sysmod": {"hello": hello}})
    router_mod._sig_cache.clear()
    yield "deadbeef0000", hello
    router_mod._sig_cache.clear()


def test_type_hints_resolved_once_across_repeated_calls(system_module, monkeypatch):
    """Dispatching the same remote function twice must only reflect its type
    hints once. The second call should hit the cache, not redo the work."""
    hash_, hello = system_module

    calls = []
    real_get_type_hints = typing_mod.get_type_hints

    def counting(fn, *a, **kw):
        if fn is hello:
            calls.append(fn)
        return real_get_type_hints(fn, *a, **kw)

    monkeypatch.setattr(typing_mod, "get_type_hints", counting)

    _call(_make_environ(f"/_fymo/remote/{hash_}/hello", ["alice"]))
    _call(_make_environ(f"/_fymo/remote/{hash_}/hello", ["bob"]))

    assert len(calls) == 1, (
        f"expected typing.get_type_hints to run once for 'hello' across two "
        f"dispatches, it ran {len(calls)} times"
    )


def test_cache_invalidates_when_function_object_changes(system_module, monkeypatch):
    """A different function landing under the same (module, fn_name) key
    (e.g. a provider swapping in a new version) must be picked up, not
    shadowed by the stale cached signature."""
    hash_, hello = system_module

    # Warm the cache with the original str-typed signature.
    _call(_make_environ(f"/_fymo/remote/{hash_}/hello", ["alice"]))

    def hello_v2(name: int) -> str:
        return f"v2 {name}"

    monkeypatch.setattr(router_mod, "_system_modules", {"sysmod": {"hello": hello_v2}})

    (_, _), body = _call(_make_environ(f"/_fymo/remote/{hash_}/hello", ["alice"]))

    # If the stale (str) signature were still cached, a str arg would validate
    # fine against hello_v2 too. With correct identity-based invalidation,
    # hello_v2's (int) signature rejects it.
    assert body["type"] == "error"
    assert body["status"] == 422
