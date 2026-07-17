"""WSGI handler for POST /_fymo/remote/<hash>/<fn>."""
import base64
import importlib
import inspect
import json
import os
import sys
import traceback
import typing
from typing import Iterable, Callable

from fymo.remote import devalue
from fymo.remote.adapters import validate_args
from fymo.remote.context import request_scope
from fymo.remote.discovery import is_exposed_remote_fn
from fymo.remote.errors import RemoteError, Redirect
from fymo.remote.identity import _ensure_uid
from fymo.remote.rate_limit import enforce_rate_limit

try:
    import pydantic
    _has_pydantic = True
except ImportError:
    _has_pydantic = False

_MAX_BODY = 1 * 1024 * 1024
_PATH_PREFIX = "/_fymo/remote/"


# Hash → module-name lookup. Overridable in tests; production is wired via
# fymo.core.server when ManifestCache is available.
_resolve_module_for_hash: Callable[[str], "str | None"] = lambda h: None

# Dev mode: when True, 500 responses include traceback + exception message.
# When False (production), 500 responses are opaque. Set by fymo.core.server.
_dev_mode: bool = False

# Mirrors discovery's `remote.explicit_optin` config flag (fymo.yml). When
# True, an app-module function must carry `__fymo_remote__` (set by
# @fymo.remote.remote) to be dispatchable — anything else 404s as
# unknown_function, matching what discovery excludes from the manifest.
# Default False preserves today's behavior: any public typed function in
# app/remote/*.py is callable. Set by fymo.core.server, same as _dev_mode.
# Does not apply to system/provider modules (_system_modules) — those are
# curated by the provider, not scanned from app source.
_explicit_optin: bool = False


def _200(
    start_response,
    payload: dict,
    set_cookie: "str | None" = None,
    extra_cookies: "list[str] | None" = None,
) -> Iterable[bytes]:
    body = json.dumps(payload).encode("utf-8")
    headers = [
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
    ]
    if set_cookie:
        headers.append(("Set-Cookie", set_cookie))
    if extra_cookies:
        for c in extra_cookies:
            headers.append(("Set-Cookie", c))
    start_response("200 OK", headers)
    return [body]


def _remote_error_payload(e: RemoteError) -> dict:
    """Envelope body for a RemoteError. RateLimited additionally carries
    retry_after, surfaced so clients can back off instead of retrying blind."""
    payload = {"type": "error", "status": e.status, "error": e.code, "message": str(e)}
    retry_after = getattr(e, "retry_after", None)
    if retry_after is not None:
        payload["retry_after"] = retry_after
    return payload


def _b64url_decode(s: str) -> str:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad).decode("utf-8")


def _origin_ok(environ: dict) -> bool:
    """Reject only when Origin is present AND mismatches Host."""
    origin = environ.get("HTTP_ORIGIN")
    if not origin:
        return True
    host = environ.get("HTTP_HOST")
    if not host:
        return True
    scheme = environ.get("wsgi.url_scheme", "http")
    expected = f"{scheme}://{host}"
    return origin == expected


def _evict_stale_app_cache() -> None:
    """Evict app.* packages from sys.modules if the app package's project
    root is no longer on sys.path.

    Handles test isolation and live-reload scenarios where the app package
    directory changes between requests (e.g. a test session that builds a
    fresh "app" package under a new tmp_path for every test, or a dev
    server whose project root moves).

    The check compares sys.path against the PARENT of app.__path__ (the
    project root that FymoApp.__init__ inserts into sys.path once, e.g.
    "/proj"), not app.__path__ itself (the "app" subdirectory it points at,
    e.g. "/proj/app"). sys.path holds project roots; it never holds the
    "app" subdirectory directly. Comparing __path__ verbatim against
    sys.path therefore never matched, so this used to evict and force a
    full reimport of every app.* module on every single call, defeating
    any caching keyed on the resulting function objects' identity even
    though the project root never actually changed between requests.
    """
    app_mod = sys.modules.get("app")
    if app_mod is None:
        return
    app_paths = list(getattr(app_mod, "__path__", []))
    if not app_paths:
        return
    if not any(os.path.dirname(p) in sys.path for p in app_paths):
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]


# Framework-shipped remote modules (e.g. `auth`), populated at startup by
# fymo.core.server from the active auth providers: {module: {fn_name: callable}}.
# This replaces the old hardcoded module→import-path table — providers are the
# single source of truth for what ships.
_system_modules: "dict[str, dict[str, Callable]]" = {}


def set_system_modules(modules: "dict[str, dict[str, Callable]]") -> None:
    global _system_modules
    _system_modules = modules


# (module_name, fn_name) -> (fn, signature, hints). inspect.signature and
# typing.get_type_hints both do real reflection work (walking parameters,
# resolving string/forward-ref annotations against the defining module's
# globals) that produces the same result every time for a given function
# object; it only needs to change when the function object itself does.
# Keyed on identity rather than a version counter or explicit invalidation:
# a reload that produces a new function object (e.g. importlib.reload, or a
# fresh module import for the same module_name) naturally makes `cached_fn
# is not fn` true, so the stale entry is replaced on the next lookup with no
# extra bookkeeping.
_sig_cache: "dict[tuple[str, str], tuple[Callable, inspect.Signature, dict]]" = {}


def _sig_and_hints(cache_key: "tuple[str, str]", fn: Callable):
    cached = _sig_cache.get(cache_key)
    if cached is not None and cached[0] is fn:
        return cached[1], cached[2]
    sig = inspect.signature(fn)
    hints = typing.get_type_hints(fn, include_extras=True)
    _sig_cache[cache_key] = (fn, sig, hints)
    return sig, hints


def _resolve_fn_in_module(module_name: str, fn_name: str):
    if not fn_name.replace("_", "").isalnum() or fn_name.startswith("_"):
        return None, None, None

    # System modules are an explicit allowlist of curated callables — look the
    # function up directly, no import or __module__ dance needed.
    if module_name in _system_modules:
        fn = _system_modules[module_name].get(fn_name)
        if fn is None:
            return None, None, None
        sig, hints = _sig_and_hints((module_name, fn_name), fn)
        return fn, sig, hints

    if not module_name.replace("_", "").isalnum():
        return None, None, None
    _evict_stale_app_cache()
    full = f"app.remote.{module_name}"
    try:
        mod = importlib.import_module(full)
    except ImportError:
        return None, None, None
    fn = getattr(mod, fn_name, None)
    if fn is None or not is_exposed_remote_fn(fn, full, _explicit_optin):
        return None, None, None
    sig, hints = _sig_and_hints((module_name, fn_name), fn)
    return fn, sig, hints


def handle_remote(environ: dict, start_response) -> Iterable[bytes]:
    # 1. CSRF: POST-only. A browser attaches cookies to top-level GETs
    # (<img>, <script>, <link>, top-level navigation) but sends no Origin for
    # them, so the Origin check below cannot stop `<img src=".../logout">`.
    # Restricting to POST closes that vector; cross-origin fetch/form POSTs
    # always carry an Origin, which step 2 then verifies.
    if environ.get("REQUEST_METHOD") != "POST":
        return _200(start_response, {"type": "error", "status": 405, "error": "method_not_allowed"})

    # 2. CSRF: Origin === Host
    if not _origin_ok(environ):
        return _200(start_response, {"type": "error", "status": 403, "error": "cross_origin"})

    # 3. Parse path
    path = environ.get("PATH_INFO", "")
    if not path.startswith(_PATH_PREFIX):
        return _200(start_response, {"type": "error", "status": 400, "error": "bad_path"})
    rest = path[len(_PATH_PREFIX):]
    parts = rest.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return _200(start_response, {"type": "error", "status": 400, "error": "bad_path"})
    hash_, fn_name = parts

    # 4. Hash → module
    module_name = _resolve_module_for_hash(hash_)
    if module_name is None:
        return _200(start_response, {"type": "error", "status": 404, "error": "unknown_module"})

    # 5. Resolve function in module
    fn, sig, hints = _resolve_fn_in_module(module_name, fn_name)
    if fn is None:
        return _200(start_response, {"type": "error", "status": 404, "error": "unknown_function"})

    # 5b. Per-function rate limit (@rate_limit marker). Checked before body
    # parse and arg validation so an over-budget caller never reaches the
    # function or its validation. For scope="ip"/"uid" the check costs only
    # a cookie HMAC and a token-bucket lookup; scope="user" additionally
    # pays an identity-resolution pass, shared with the handler's
    # current_uid() via the request event (see rate_limit.py's docstring
    # for the cost trade-off, which the WSGI edge limiter bounds).
    limited = enforce_rate_limit(fn, (module_name, fn_name), environ)
    if limited is not None:
        return _200(start_response, _remote_error_payload(limited))

    # 6. Body parse + payload decode
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > _MAX_BODY:
        return _200(start_response, {"type": "error", "status": 413, "error": "too_large"})
    raw = environ["wsgi.input"].read(length) if length else b"{}"
    try:
        body = json.loads(raw or b"{}")
        payload_b64 = body.get("payload", "")
        # "[[]]" is devalue.stringify([]): a missing/empty payload means a
        # zero-arg call, so the fallback must parse to an empty args list.
        payload_str = _b64url_decode(payload_b64) if payload_b64 else "[[]]"
        args = devalue.parse(payload_str)
        if not isinstance(args, list):
            raise ValueError("payload must devalue-parse to a list of args")
    except Exception as e:
        return _200(start_response, {"type": "error", "status": 400, "error": "bad_payload", "message": str(e)})

    # 7. Validate args
    try:
        validated = validate_args(args, sig, hints)
    except Exception as e:
        if _has_pydantic and isinstance(e, pydantic.ValidationError):
            return _200(start_response, {"type": "error", "status": 422, "error": "validation", "issues": e.errors()})
        return _200(start_response, {"type": "error", "status": 422, "error": "validation", "message": str(e)})

    # 8. Identity + dispatch. Auth scope wraps the call so signup/login/logout
    # can queue Set-Cookie values; we drain that queue alongside the uid cookie.
    uid, set_cookie = _ensure_uid(environ)
    extra_cookies: "list[str]" = []
    auth_token = None
    try:
        from fymo.auth.context import start_auth_scope, end_auth_scope, consume_pending_cookies
        auth_token = start_auth_scope()
    except ImportError:
        consume_pending_cookies = lambda: []  # type: ignore[assignment]
        end_auth_scope = lambda _t: None  # type: ignore[assignment]

    try:
        try:
            with request_scope(uid=uid, environ=environ):
                result = fn(*validated)
        except RemoteError as e:
            extra_cookies = consume_pending_cookies()
            if isinstance(e, Redirect):
                return _200(
                    start_response,
                    {"type": "redirect", "location": e.location, "status": e.status},
                    set_cookie, extra_cookies,
                )
            return _200(start_response, _remote_error_payload(e), set_cookie, extra_cookies)
        except Exception as e:
            extra_cookies = consume_pending_cookies()
            payload = {"type": "error", "status": 500, "error": "internal"}
            if _dev_mode:
                payload["message"] = str(e)
                payload["traceback"] = traceback.format_exc()
            return _200(start_response, payload, set_cookie, extra_cookies)
        extra_cookies = consume_pending_cookies()
    finally:
        if auth_token is not None:
            end_auth_scope(auth_token)

    # 9. Encode response via devalue
    try:
        encoded = devalue.stringify(result)
    except Exception as e:
        payload = {"type": "error", "status": 500, "error": "encode_failed"}
        if _dev_mode:
            payload["message"] = str(e)
        return _200(start_response, payload, set_cookie, extra_cookies)

    return _200(start_response, {"type": "result", "result": encoded}, set_cookie, extra_cookies)
