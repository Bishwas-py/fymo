"""The /_fymo/broadcast/<module>/<channel> SSE endpoint.

The browser-facing half of broadcasts: the generated `$broadcast` client
opens an EventSource here; this handler resolves the channel from
discovery, runs its body as the subscribe-time authorization guard, and
streams the provider's events as SSE frames until the client disconnects.

Each open subscription occupies a thread for its lifetime — fine on the
threaded dev server and gunicorn `--worker-class gthread`; fatal on sync
workers (documented deployment requirement in the design spec).
"""
from __future__ import annotations

import inspect
import json
import logging
from typing import Iterator
from urllib.parse import parse_qsl

from fymo.broadcast import channel_key, get_broadcast_provider, get_channels

logger = logging.getLogger("fymo.broadcast")

_PATH_PREFIX = "/_fymo/broadcast/"


def _error(start_response, status: str, message: str):
    body = json.dumps({"error": message}).encode()
    start_response(status, [
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-cache"),
    ])
    return [body]


def _run_guard(fn, bound_args: dict, environ: dict) -> bool:
    """Run the channel body as the authorization guard, inside the same
    request scope remote functions get, so current_uid() works. Allow
    unless the body raises or returns exactly False (`...`/None bodies —
    the open-channel case — allow)."""
    from fymo.remote.context import request_scope
    from fymo.remote.identity import _ensure_uid

    uid, _set_cookie = _ensure_uid(environ)
    with request_scope(uid=uid, environ=environ):
        result = fn(**bound_args)
    return result is not False


def handle_broadcast(environ, start_response):
    """WSGI handler for GET /_fymo/broadcast/<module>/<channel>?<args>."""
    path = environ.get("PATH_INFO", "")
    rest = path[len(_PATH_PREFIX):] if path.startswith(_PATH_PREFIX) else path.strip("/")
    parts = [p for p in rest.strip("/").split("/") if p]
    if len(parts) != 2:
        return _error(start_response, "400 BAD REQUEST", "expected /_fymo/broadcast/<module>/<channel>")
    module, channel = parts

    channels = get_channels()
    entry = channels.get(channel)
    if entry is None or entry[0] != module:
        return _error(start_response, "404 NOT FOUND", f"unknown broadcast channel: {module}/{channel}")
    _, fn = entry

    args = dict(parse_qsl(environ.get("QUERY_STRING", "")))
    try:
        bound = inspect.signature(fn).bind(**args)
        bound.apply_defaults()
    except TypeError as e:
        return _error(start_response, "422 UNPROCESSABLE ENTITY", f"subscribe args do not match channel signature: {e}")

    try:
        allowed = _run_guard(fn, dict(bound.arguments), environ)
    except Exception as e:
        logger.info("broadcast guard rejected %s/%s: %s", module, channel, e)
        allowed = False
    if not allowed:
        return _error(start_response, "403 FORBIDDEN", "subscription rejected")

    key = channel_key(module, channel, dict(bound.arguments))
    provider = get_broadcast_provider()

    start_response("200 OK", [
        ("Content-Type", "text/event-stream"),
        ("Cache-Control", "no-cache"),
        ("X-Accel-Buffering", "no"),  # tell nginx-style proxies not to buffer
    ])

    def stream() -> Iterator[bytes]:
        # First frame immediately: EventSource fires `open` only once bytes
        # arrive through every proxy hop, and it flushes those hops early.
        yield b": subscribed\n\n"
        events = provider.listen(key)
        try:
            for event in events:
                if event is None:  # provider idle tick -> keepalive; writing
                    yield b": keepalive\n\n"  # it detects dead clients too
                else:
                    yield b"data: " + event.encode("utf-8") + b"\n\n"
        finally:
            events.close()  # releases the provider's connection on disconnect

    return stream()
