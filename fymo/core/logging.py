"""Structured logging for fymo.

`configure(dev, config, project_root)` installs exactly one fymo-owned handler
on the ROOT logger, so fymo's logs, the app's own `logging.getLogger(...)` output,
and library logs (e.g. Procrastinate in the jobs worker) all flow to one destination
in one format. Configurable via fymo.yml's `logging:` section: `destination`
(terminal/file), `file` (path for file destination), `level` (debug/info/warning/error,
defaults to info), `format` (text/json; defaults to text in dev, json in prod).
`access_log(environ, status, duration_ms)` emits exactly one line per completed
request. `resolve_logging_config()` validates fymo.yml's `logging:` section into
a LoggingSettings dataclass with fail-fast ValueError on bad keys.

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
_installed_handler: Optional[logging.Handler] = None

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


class _FymoFormatter(logging.Formatter):
    """One formatter for every record passing through fymo's handler.

    fymo's own records ("fymo" / "fymo.*" loggers) arrive pre-rendered by
    access_log/job_log — in json mode they're already JSON lines, in text
    mode already human lines — so they pass through untouched. Records
    from app code and libraries get wrapped: json mode produces
    {"logger", "level", "message"} objects, text mode produces
    "LEVEL logger: message". Tracebacks (exc_info) are appended in text
    mode / added as an "exc_info" key in json mode.
    """

    def __init__(self, json_mode: bool):
        super().__init__()
        self._json = json_mode

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        is_fymo = record.name == "fymo" or record.name.startswith("fymo.")
        exc_text = self.formatException(record.exc_info) if record.exc_info else None

        if self._json:
            if is_fymo and message.startswith("{"):
                if exc_text is None:
                    return message
                payload = _json.loads(message)
                payload["exc_info"] = exc_text
                return _json.dumps(payload)
            payload = {"logger": record.name, "level": record.levelname, "message": message}
            if exc_text is not None:
                payload["exc_info"] = exc_text
            return _json.dumps(payload)

        out = message if is_fymo else f"{record.levelname} {record.name}: {message}"
        if exc_text is not None:
            out = f"{out}\n{exc_text}"
        return out


def configure(
    dev: bool = False,
    config: Optional[dict] = None,
    project_root: Optional[Path] = None,
) -> None:
    """(Re)configure process-wide logging from fymo.yml's `logging:` section.

    Installs exactly one fymo-owned handler on the ROOT logger, so fymo's
    logs, the app's own `logging.getLogger(...)` output, and library logs
    (e.g. Procrastinate in the jobs worker) all flow to one destination in
    one format. Idempotent: reconfiguring removes only the handler fymo
    itself installed — pytest's caplog and any user-attached handlers are
    never touched.

    Raises ValueError on invalid config (see resolve_logging_config) —
    fail-fast at startup rather than logging to the wrong place silently.
    """
    global _json_mode, _installed_handler

    settings = resolve_logging_config(dev=dev, config=config, project_root=project_root)
    _json_mode = settings.json

    root = logging.getLogger()
    if _installed_handler is not None:
        root.removeHandler(_installed_handler)
        _installed_handler.close()
        _installed_handler = None

    if settings.destination == "file":
        assert settings.file is not None  # guaranteed by resolve_logging_config
        settings.file.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.FileHandler(settings.file, mode="a", encoding="utf-8")
    else:
        handler = logging.StreamHandler()

    handler.setFormatter(_FymoFormatter(settings.json))
    handler.setLevel(settings.level)
    root.addHandler(handler)
    # Root defaults to WARNING, which would filter INFO records from app
    # loggers before the handler ever sees them — the level knob must
    # govern end to end.
    root.setLevel(settings.level)
    _installed_handler = handler


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
