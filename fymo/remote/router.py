"""WSGI handler for POST /_fymo/remote/<hash>/<fn>."""
import base64
import importlib
import inspect
import json
import sys
import traceback
import typing
from typing import Iterable, Callable

from fymo.remote import devalue
from fymo.remote.adapters import validate_args
from fymo.remote.context import request_scope
from fymo.remote.errors import RemoteError
from fymo.remote.identity import _ensure_uid

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


def _200(start_response, payload: dict, set_cookie: "str | None" = None) -> Iterable[bytes]:
    body = json.dumps(payload).encode("utf-8")
    headers = [
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
    ]
    if set_cookie:
        headers.append(("Set-Cookie", set_cookie))
    start_response("200 OK", headers)
    return [body]


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
    """Evict app.* packages from sys.modules if the app package root is no longer on sys.path.

    Handles test isolation and live-reload scenarios where the app package
    directory changes between requests.
    """
    app_mod = sys.modules.get("app")
    if app_mod is None:
        return
    app_paths = list(getattr(app_mod, "__path__", []))
    if not app_paths:
        return
    if not any(p in sys.path for p in app_paths):
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]


def _resolve_fn_in_module(module_name: str, fn_name: str):
    if not module_name.replace("_", "").isalnum():
        return None, None, None
    if not fn_name.replace("_", "").isalnum() or fn_name.startswith("_"):
        return None, None, None
    _evict_stale_app_cache()
    full = f"app.remote.{module_name}"
    try:
        mod = importlib.import_module(full)
    except ImportError:
        return None, None, None
    fn = getattr(mod, fn_name, None)
    if fn is None or not callable(fn) or getattr(fn, "__module__", None) != full:
        return None, None, None
    return fn, inspect.signature(fn), typing.get_type_hints(fn, include_extras=True)


def handle_remote(environ: dict, start_response) -> Iterable[bytes]:
    # 1. CSRF: Origin === Host
    if not _origin_ok(environ):
        return _200(start_response, {"type": "error", "status": 403, "error": "cross_origin"})

    # 2. Parse path
    path = environ.get("PATH_INFO", "")
    if not path.startswith(_PATH_PREFIX):
        return _200(start_response, {"type": "error", "status": 400, "error": "bad_path"})
    rest = path[len(_PATH_PREFIX):]
    parts = rest.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return _200(start_response, {"type": "error", "status": 400, "error": "bad_path"})
    hash_, fn_name = parts

    # 3. Hash → module
    module_name = _resolve_module_for_hash(hash_)
    if module_name is None:
        return _200(start_response, {"type": "error", "status": 404, "error": "unknown_module"})

    # 4. Resolve function in module
    fn, sig, hints = _resolve_fn_in_module(module_name, fn_name)
    if fn is None:
        return _200(start_response, {"type": "error", "status": 404, "error": "unknown_function"})

    # 5. Body parse + payload decode
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
        payload_str = _b64url_decode(payload_b64) if payload_b64 else "[1,[]]"
        args = devalue.parse(payload_str)
        if not isinstance(args, list):
            raise ValueError("payload must devalue-parse to a list of args")
    except Exception as e:
        return _200(start_response, {"type": "error", "status": 400, "error": "bad_payload", "message": str(e)})

    # 6. Validate args
    try:
        validated = validate_args(args, sig, hints)
    except Exception as e:
        if _has_pydantic and isinstance(e, pydantic.ValidationError):
            return _200(start_response, {"type": "error", "status": 422, "error": "validation", "issues": e.errors()})
        return _200(start_response, {"type": "error", "status": 422, "error": "validation", "message": str(e)})

    # 7. Identity + dispatch
    uid, set_cookie = _ensure_uid(environ)
    try:
        with request_scope(uid=uid, environ=environ):
            result = fn(*validated)
    except RemoteError as e:
        return _200(start_response, {"type": "error", "status": e.status, "error": e.code, "message": str(e)}, set_cookie)
    except Exception as e:
        payload = {"type": "error", "status": 500, "error": "internal"}
        if _dev_mode:
            payload["message"] = str(e)
            payload["traceback"] = traceback.format_exc()
        return _200(start_response, payload, set_cookie)

    # 8. Encode response via devalue
    try:
        encoded = devalue.stringify(result)
    except Exception as e:
        payload = {"type": "error", "status": 500, "error": "encode_failed"}
        if _dev_mode:
            payload["message"] = str(e)
        return _200(start_response, payload, set_cookie)

    return _200(start_response, {"type": "result", "result": encoded}, set_cookie)
