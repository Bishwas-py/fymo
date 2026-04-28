"""WSGI handler for POST /__remote/<module>/<fn>."""
import importlib
import inspect
import json
import sys
import traceback
import typing
from typing import Iterable

from fymo.remote.adapters import validate_args, serialize_response
from fymo.remote.context import request_scope
from fymo.remote.errors import RemoteError
from fymo.remote.identity import _ensure_uid

try:
    import pydantic
    _has_pydantic = True
except ImportError:
    _has_pydantic = False

_MAX_BODY = 1 * 1024 * 1024


def _json_response(start_response, status: int, payload: dict, set_cookie: str | None = None) -> Iterable[bytes]:
    body = json.dumps(payload).encode("utf-8")
    headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
    if set_cookie:
        headers.append(("Set-Cookie", set_cookie))
    statuses = {
        200: "200 OK", 400: "400 Bad Request", 401: "401 Unauthorized",
        403: "403 Forbidden", 404: "404 Not Found", 409: "409 Conflict",
        413: "413 Payload Too Large", 422: "422 Unprocessable Entity",
        500: "500 Internal Server Error",
    }
    start_response(statuses.get(status, f"{status} Status"), headers)
    return [body]


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
    # If none of the app package's paths appear in sys.path, the cached module is stale.
    if not any(p in sys.path for p in app_paths):
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]


def _resolve(module_name: str, fn_name: str):
    """Return (fn, signature, hints) or (None, None, None)."""
    if not module_name.replace("_", "").isalnum() or not fn_name.replace("_", "").isalnum():
        return None, None, None
    if fn_name.startswith("_"):
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
    sig = inspect.signature(fn)
    hints = typing.get_type_hints(fn, include_extras=True)
    return fn, sig, hints


def handle_remote(environ: dict, start_response) -> Iterable[bytes]:
    path = environ.get("PATH_INFO", "")
    parts = path[len("/__remote/"):].split("/")
    if len(parts) != 2:
        return _json_response(start_response, 400, {"ok": False, "error": "bad_path"})
    module_name, fn_name = parts

    fn, sig, hints = _resolve(module_name, fn_name)
    if fn is None:
        return _json_response(start_response, 404, {"ok": False, "error": "unknown_function"})

    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > _MAX_BODY:
        return _json_response(start_response, 413, {"ok": False, "error": "too_large"})

    raw = environ["wsgi.input"].read(length) if length else b"{}"
    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return _json_response(start_response, 400, {"ok": False, "error": "invalid_json"})

    args = body.get("args") or []
    try:
        validated = validate_args(args, sig, hints)
    except Exception as e:
        if _has_pydantic and isinstance(e, pydantic.ValidationError):
            return _json_response(start_response, 422, {"ok": False, "error": "validation", "issues": e.errors()})
        return _json_response(start_response, 422, {"ok": False, "error": "validation", "message": str(e)})

    uid, set_cookie = _ensure_uid(environ)

    try:
        with request_scope(uid=uid, environ=environ):
            result = fn(*validated)
    except RemoteError as e:
        return _json_response(start_response, e.status, {"ok": False, "error": e.code, "message": str(e)}, set_cookie)
    except Exception as e:
        return _json_response(start_response, 500,
                              {"ok": False, "error": "internal", "message": str(e), "traceback": traceback.format_exc()},
                              set_cookie)

    serialized = serialize_response(result, hints.get("return"))
    return _json_response(start_response, 200, {"ok": True, "data": serialized}, set_cookie)
