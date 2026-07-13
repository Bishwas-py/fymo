"""Structured logging for fymo.

Two knobs: `configure(json=...)` sets the output format for the process —
human-readable text in dev, one JSON object per line in prod (FYMO_DEV=0).
`access_log(environ, status, duration_ms)` emits exactly one line per
completed request.

PII/secret hygiene: access_log only ever reads REQUEST_METHOD and PATH_INFO
from `environ`. It must never be extended to log cookies, request bodies,
or auth headers.

Quiet by default: importing this module attaches no output handler, so
merely constructing a FymoApp in a test that never calls configure()
produces no stdout noise. `configure()` is idempotent — safe to call every
time a FymoApp starts up, including many times across a test session,
without piling up duplicate handlers/output.
"""
from __future__ import annotations

import json as _json
import logging

logger = logging.getLogger("fymo")
logger.addHandler(logging.NullHandler())

_json_mode = False


def configure(json: bool = False) -> None:
    """(Re)configure the "fymo" logger's access-log output format.

    json=True: one compact JSON object per line (prod). json=False: a
    plain human-readable line (dev). Clears any previously attached
    handlers first so repeated calls (e.g. one per FymoApp instance in a
    test run) never accumulate duplicate handlers or duplicate output.
    """
    global _json_mode
    _json_mode = bool(json)

    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = True


def access_log(environ: dict, status: str, duration_ms: float) -> None:
    """Emit one access-log line for a completed request.

    Only method, path, status, and duration are logged. Never cookie
    values, request bodies, or auth headers — those may carry secrets or
    PII and must never end up in logs.
    """
    method = environ.get("REQUEST_METHOD", "-")
    path = environ.get("PATH_INFO", "-")
    try:
        status_code = int(str(status).split(" ", 1)[0])
    except (ValueError, IndexError):
        status_code = 0
    duration = round(float(duration_ms), 2)

    if _json_mode:
        message = _json.dumps({
            "method": method,
            "path": path,
            "status": status_code,
            "duration_ms": duration,
        })
    else:
        message = f'{method} {path} {status_code} {duration}ms'

    logger.info(message)
