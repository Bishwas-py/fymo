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
from typing import Any, Callable, Dict, List, Optional

from fymo.core.http import HttpRoute

# Reserved by FymoApp._dispatch itself (fymo/core/server.py), checked before
# the app-routes loop runs. A `media:` prefix landing under either of these
# would silently never be reached, so it's worth a loud warning at startup
# rather than a confusing 404/wrong-content-type discovered in production.
_RESERVED_PREFIXES = ("/dist/", "/assets/")


def _respond_error(start_response, status: str, message: bytes):
    start_response(status, [
        ("Content-Type", "text/plain"),
        ("Content-Length", str(len(message))),
    ])
    return [message]


def _respond_range_not_satisfiable(start_response, file_size: int):
    """416, per RFC 7233 section 4.4. The `Content-Range: bytes */<size>`
    form (no start-end pair) tells the client what range would have been
    valid, without the server needing to open the file to serve nothing."""
    body = b"range not satisfiable"
    start_response("416 Range Not Satisfiable", [
        ("Content-Type", "text/plain"),
        ("Content-Length", str(len(body))),
        ("Content-Range", f"bytes */{file_size}"),
    ])
    return [body]


def _is_traversal_safe(filename: str) -> bool:
    """Cheap first check: no '..' segments and no absolute path. Checked as
    plain substring/prefix tests, because `root_dir / filename` would
    happily let a leading '/' override root_dir entirely, pathlib treats
    joining with an absolute path as a replacement, not a traversal, so the
    unsafe case has to be rejected before the join ever happens. This alone
    is not sufficient against a symlink physically planted inside root_dir
    that points elsewhere (its own filename contains neither '..' nor a
    leading '/'), which is what `_resolve_within` below is for."""
    return ".." not in filename and not filename.startswith("/")


def _resolve_within(root_dir: Path, filename: str) -> Optional[Path]:
    """Join `filename` onto `root_dir` and confirm the fully-resolved path,
    symlinks included, is still contained within `root_dir`. Returns None if
    it escapes. This covers both any traversal that slipped past
    `_is_traversal_safe` and a symlink planted inside root_dir that points
    outside it, since following the symlink target is exactly what
    `Path.resolve()` does. `root_dir` is assumed already resolved (done once
    in `build_media_routes`, not per request)."""
    candidate = (root_dir / filename).resolve()
    if candidate != root_dir and not candidate.is_relative_to(root_dir):
        return None
    return candidate


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

        resolved_path = _resolve_within(root_dir, filename)
        if resolved_path is None:
            return _respond_error(start_response, "400 Bad Request", b"invalid filename")

        if not resolved_path.is_file():
            return _respond_error(start_response, "404 Not Found", b"not found")

        content_type, _ = mimetypes.guess_type(filename)
        content_type = content_type or "application/octet-stream"
        file_size = resolved_path.stat().st_size
        range_header = environ.get("HTTP_RANGE")

        if range_header:
            # Single-range only ("bytes=start-end"), matching the app-level
            # handlers this replaces. Multi-range (comma-separated) isn't
            # something video/audio scrubbing needs and would require a
            # multipart/byteranges body.
            range_spec = range_header.split("=", 1)[-1]
            start_str, _, end_str = range_spec.partition("-")
            try:
                if start_str == "":
                    # Suffix-byte-range-spec ("bytes=-N"): the last N bytes,
                    # not "bytes 0 through N". An empty start_str here is
                    # the RFC 7233 suffix form, not a missing/defaulted start.
                    if end_str == "":
                        raise ValueError("empty range spec")
                    suffix_length = int(end_str)
                    if suffix_length < 0:
                        raise ValueError("negative suffix length")
                    if suffix_length == 0 or file_size == 0:
                        return _respond_range_not_satisfiable(start_response, file_size)
                    start = max(0, file_size - suffix_length)
                    end = file_size - 1
                else:
                    start = int(start_str)
                    end = int(end_str) if end_str else file_size - 1
            except ValueError:
                return _respond_error(start_response, "400 Bad Request", b"malformed range header")

            # Unsatisfiable per RFC 7233 section 2.1: start at/past EOF, or
            # an end before start. Caught here, before any arithmetic feeds
            # into f.read(), so a crafted start like 999999999 on a small
            # file can never turn into a negative read length.
            if start < 0 or start >= file_size or end < start:
                return _respond_range_not_satisfiable(start_response, file_size)

            end = min(end, file_size - 1)
            chunk_size = end - start + 1
            with open(resolved_path, "rb") as f:
                f.seek(start)
                data = f.read(chunk_size)
            start_response("206 Partial Content", [
                ("Content-Range", f"bytes {start}-{end}/{file_size}"),
                ("Accept-Ranges", "bytes"),
                ("Content-Length", str(chunk_size)),
                ("Content-Type", content_type),
            ])
            return [data]

        data = resolved_path.read_bytes()
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
    vast majority, pre-existing and new alike) register zero extra routes.

    Raises `ValueError` for an entry missing `prefix` or `dir` (a plain
    KeyError at startup would point at the wrong place, this names the bad
    entry). A prefix colliding with a reserved fymo prefix only warns
    (printed, matching ConfigManager's own warning style in
    fymo/core/config.py) rather than raising, since it's a config smell
    worth flagging loudly, not a guaranteed misconfiguration fymo should
    refuse to boot over."""
    routes: List[HttpRoute] = []
    for entry in media_config:
        if "prefix" not in entry or "dir" not in entry:
            raise ValueError(
                f"media: entry is missing required key(s) 'prefix' and/or 'dir': {entry!r}"
            )
        prefix = entry["prefix"]
        for reserved in _RESERVED_PREFIXES:
            if prefix.startswith(reserved) or reserved.startswith(prefix):
                print(
                    f"Warning: media: prefix {prefix!r} overlaps with fymo's "
                    f"reserved {reserved!r} route, which is matched first and "
                    f"will always win. This media route may never be reached."
                )
        root_dir = (Path(project_root) / entry["dir"]).resolve()
        extensions = {str(e).lower().lstrip(".") for e in entry.get("extensions", [])}
        routes.append(HttpRoute(
            method="GET",
            path=prefix,
            handler=_make_media_handler(prefix, root_dir, extensions),
        ))
    return routes
