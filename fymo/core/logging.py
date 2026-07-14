"""Structured logging for fymo.

Two knobs: `configure(json=...)` sets the output format for the process —
human-readable text in dev, one JSON object per line in prod (FYMO_DEV=0).
`access_log(environ, status, duration_ms)` emits exactly one line per
completed request. `resolve_logging_config()` validates fymo.yml's `logging:`
section into a LoggingSettings dataclass with fail-fast ValueError on bad keys.

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
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("fymo")
logger.addHandler(logging.NullHandler())

_json_mode = False

_DESTINATIONS = ("terminal", "file")
_FORMATS = ("text", "json")
_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


@dataclass(frozen=True)
class LoggingSettings:
    """Validated logging configuration, resolved from fymo.yml's `logging:`
    section plus the dev flag. `file` is set iff destination == "file"."""
    destination: str
    file: Optional[Path]
    level: int
    json: bool


def resolve_logging_config(
    dev: bool = False,
    config: Optional[dict] = None,
    project_root: Optional[Path] = None,
) -> LoggingSettings:
    """Validate fymo.yml's `logging:` section into LoggingSettings.

    Fail-fast by design: a bad value raises ValueError naming the key and
    the allowed values, instead of silently falling back — logging that
    quietly ends up somewhere unexpected is how production incidents go
    unrecorded. An absent/empty section is NOT an error; every key has a
    default (terminal, info, text-in-dev/json-in-prod).
    """
    cfg = config or {}

    destination = str(cfg.get("destination", "terminal")).lower()
    if destination not in _DESTINATIONS:
        raise ValueError(
            f"logging.destination must be one of {_DESTINATIONS}, got {destination!r}"
        )

    file_path: Optional[Path] = None
    if destination == "file":
        file_value = cfg.get("file")
        if not file_value:
            raise ValueError(
                "logging.destination is 'file' but logging.file is not set "
                "— add e.g. `file: log/fymo.log` to the logging section"
            )
        file_path = Path(str(file_value))
        if not file_path.is_absolute() and project_root is not None:
            file_path = Path(project_root) / file_path

    level_name = str(cfg.get("level", "info")).lower()
    if level_name not in _LEVELS:
        raise ValueError(
            f"logging.level must be one of {tuple(_LEVELS)}, got {level_name!r}"
        )

    fmt = cfg.get("format")
    if fmt is None:
        json_mode = not dev
    else:
        fmt = str(fmt).lower()
        if fmt not in _FORMATS:
            raise ValueError(f"logging.format must be one of {_FORMATS}, got {fmt!r}")
        json_mode = fmt == "json"

    return LoggingSettings(
        destination=destination, file=file_path, level=_LEVELS[level_name], json=json_mode,
    )


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
