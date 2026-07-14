"""Declarative media serving (fymo.yml `media:` section) -> HttpRoute list.

Before this existed, apps that needed to stream a video with seek/scrub
support (or serve any other binary file family) had to hand-write a raw WSGI
handler under `app/routes.py` using the `fymo.core.http` extension point:
Range-header parsing, path-traversal validation, content-type mapping, and
404/400 handling, all repeated per app. This module lets that be declared
instead:

    media:
      - prefix: /media/videos/
        dir: data/videos
        extensions: [webm]

`build_media_routes` turns each entry into an `HttpRoute` with a WSGI
handler fymo owns, so apps get single-range byte-range support and
traversal-safe filename handling for free. The routes it returns are meant
to sit alongside `discover_app_http_routes`'s routes in `FymoApp._app_routes`
(see fymo/core/server.py) rather than replace that seam, since some apps
will still want fully custom raw-WSGI routes for things this doesn't cover
(webhooks, non-file responses, etc.).
"""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Callable, Dict, List

from fymo.core.http import HttpRoute


def _respond_error(start_response, status: str, message: bytes):
    start_response(status, [
        ("Content-Type", "text/plain"),
        ("Content-Length", str(len(message))),
    ])
    return [message]


def _is_traversal_safe(filename: str) -> bool:
    """Same rule apps were hand-writing before this feature existed: no
    '..' segments and no absolute path. Checked as plain substring/prefix
    tests (not `Path.resolve()` containment), because `root_dir / filename`
    would happily let a leading '/' override root_dir entirely. pathlib
    treats joining with an absolute path as a replacement, not a traversal,
    so the unsafe case has to be rejected before the join ever happens."""
    return ".." not in filename and not filename.startswith("/")


def _make_media_handler(prefix: str, root_dir: Path, extensions: set) -> Callable:
    """Build the WSGI handler for one `media:` entry. `extensions` is a set
    of lowercase, dot-less extensions (e.g. {"webm"}); anything else is a
    400, same as an unsafe filename, so a probing request can't distinguish
    "wrong extension" from "path traversal attempt"."""

    def handler(environ, start_response):
        path = environ.get("PATH_INFO", "")
        filename = path[len(prefix):]

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if not _is_traversal_safe(filename) or ext not in extensions:
            return _respond_error(start_response, "400 Bad Request", b"invalid filename")

        file_path = root_dir / filename
        if not file_path.is_file():
            return _respond_error(start_response, "404 Not Found", b"not found")

        content_type, _ = mimetypes.guess_type(filename)
        content_type = content_type or "application/octet-stream"
        file_size = file_path.stat().st_size
        range_header = environ.get("HTTP_RANGE")

        if range_header:
            # Single-range only ("bytes=start-end"), matching the app-level
            # handlers this replaces. Multi-range (comma-separated) isn't
            # something video/audio scrubbing needs and would require a
            # multipart/byteranges body.
            range_spec = range_header.split("=", 1)[-1]
            start_str, _, end_str = range_spec.partition("-")
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1
            end = min(end, file_size - 1)
            chunk_size = end - start + 1
            with open(file_path, "rb") as f:
                f.seek(start)
                data = f.read(chunk_size)
            start_response("206 Partial Content", [
                ("Content-Range", f"bytes {start}-{end}/{file_size}"),
                ("Accept-Ranges", "bytes"),
                ("Content-Length", str(chunk_size)),
                ("Content-Type", content_type),
            ])
            return [data]

        data = file_path.read_bytes()
        start_response("200 OK", [
            ("Accept-Ranges", "bytes"),
            ("Content-Length", str(file_size)),
            ("Content-Type", content_type),
        ])
        return [data]

    return handler


def build_media_routes(project_root: Path, media_config: List[Dict[str, Any]]) -> List[HttpRoute]:
    """Turn the `media:` fymo.yml section into `HttpRoute`s. Returns `[]`
    when `media_config` is empty, so apps without a `media:` section (the
    vast majority, pre-existing and new alike) register zero extra routes."""
    routes: List[HttpRoute] = []
    for entry in media_config:
        prefix = entry["prefix"]
        root_dir = (Path(project_root) / entry["dir"]).resolve()
        extensions = {str(e).lower().lstrip(".") for e in entry.get("extensions", [])}
        routes.append(HttpRoute(
            method="GET",
            path=prefix,
            handler=_make_media_handler(prefix, root_dir, extensions),
        ))
    return routes
