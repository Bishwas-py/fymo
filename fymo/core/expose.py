"""Declarative storage exposure (fymo.yml `storage.expose` entries) -> HttpRoute list.

Before this existed, apps that needed to stream a video with seek/scrub
support (or serve any other binary file family) had to hand-write a raw WSGI
handler under `app/routes.py` using the `fymo.core.http` extension point:
Range-header parsing, path-traversal validation, content-type mapping, and
404/400 handling, all repeated per app. This module lets that be declared
instead, nested under the storage the files are served out of:

    storage:
      provider: local
      root: data
      expose:
        - prefix: /media/videos/
          dir: videos
          extensions: [webm]

(Exposure used to be a top-level `media:` section; issue #76 folded it under
`storage:` because every entry's `dir` was already resolved through storage
and nothing in the config's shape said so. The old key is a hard boot/build
error now, see fymo.core.config.MEDIA_KEY_REMOVED_ERROR.)

`build_expose_routes` turns each entry into an `HttpRoute` with a WSGI
handler fymo owns, so apps get single-range byte-range support and
traversal-safe filename handling for free. The routes it returns are meant
to sit alongside `discover_app_http_routes`'s routes in `FymoApp._app_routes`
(see fymo/core/server.py) rather than replace that seam, since some apps
will still want fully custom raw-WSGI routes for things this doesn't cover
(webhooks, non-file responses, etc.).
"""
from __future__ import annotations

import mimetypes
import posixpath
from pathlib import Path
from typing import Any, Callable, Dict, List

from fymo.core.http import HttpRoute
from fymo.storage.base import RangeNotSatisfiable, StorageProvider

# Reserved by FymoApp._dispatch itself (fymo/core/server.py), checked before
# the app-routes loop runs. An expose prefix landing under either of these
# would silently never be reached, so it's worth a loud warning at startup
# rather than a confusing 404/wrong-content-type discovered in production.
_RESERVED_PREFIXES = ("/dist/", "/static/")

# Shared by FymoApp startup (fymo/core/server.py) and `fymo build`'s
# check_storage_required_for_expose (fymo/build/hygiene.py) so the two
# entry points can never drift on the message.
EXPOSE_WITHOUT_PROVIDER_ERROR = (
    "storage.expose is configured but storage itself is not: exposed entries "
    "serve files through the configured StorageProvider and there is no "
    "default, so storage must be configured. Set storage.provider "
    "(e.g. `storage: {provider: local, root: data}`)."
)


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


def _make_expose_handler(prefix: str, dir_key: str, extensions: set, storage: StorageProvider) -> Callable:
    """Build the WSGI handler for one `storage.expose` entry. `extensions` is a set
    of lowercase, dot-less extensions (e.g. {"webm"}); anything else is a
    400, same as an unsafe filename, so a probing request can't distinguish
    "wrong extension" from "path traversal attempt".

    `dir_key` (the entry's `dir:` value) is the storage-key namespace for
    this route, not a filesystem path. The requested filename is joined
    onto it with `posixpath.join` to produce the key handed to `storage`.
    `posixpath.join` mirrors `pathlib`'s own absolute-path-override
    behavior (a second argument starting with '/' replaces the first
    entirely rather than being appended), which is what makes a leading '/'
    in the requested filename resolve to a key that itself starts with '/'
    and gets rejected by the provider's own traversal-safety check, exactly
    as it did when this handler joined paths with pathlib directly. All
    containment/symlink-escape enforcement now lives in the storage
    provider (see fymo.storage.providers.local for the local case); this
    handler only translates the provider's ValueError/RangeNotSatisfiable
    into the right HTTP status."""

    def handler(environ, start_response):
        path = environ.get("PATH_INFO", "")
        filename = path[len(prefix):]

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in extensions:
            return _respond_error(start_response, "400 Bad Request", b"invalid filename")

        key = posixpath.join(dir_key, filename)

        try:
            found = storage.exists(key)
        except ValueError:
            return _respond_error(start_response, "400 Bad Request", b"invalid filename")

        if not found:
            return _respond_error(start_response, "404 Not Found", b"not found")

        content_type, _ = mimetypes.guess_type(filename)
        content_type = content_type or "application/octet-stream"
        file_size = storage.size(key)
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

            # Unsatisfiable-range detection (start at/past EOF, or an end
            # before start) and end-clamping both now live in the storage
            # provider's read(); RangeNotSatisfiable carries the size the
            # 416 response's Content-Range header needs.
            try:
                data = storage.read(key, range=(start, end))
            except RangeNotSatisfiable as exc:
                return _respond_range_not_satisfiable(start_response, exc.size)

            # The actual returned length is the source of truth for the end
            # of the range served (the provider may have clamped it), so
            # derive the response's Content-Range from it rather than the
            # raw (possibly past-EOF) end parsed from the request header.
            chunk_size = len(data)
            served_end = start + chunk_size - 1
            start_response("206 Partial Content", [
                ("Content-Range", f"bytes {start}-{served_end}/{file_size}"),
                ("Accept-Ranges", "bytes"),
                ("Content-Length", str(chunk_size)),
                ("Content-Type", content_type),
            ])
            return [data]

        data = storage.read(key)
        start_response("200 OK", [
            ("Accept-Ranges", "bytes"),
            ("Content-Length", str(file_size)),
            ("Content-Type", content_type),
        ])
        return [data]

    return handler


def build_expose_routes(
    project_root: Path, expose_config: List[Dict[str, Any]], storage: StorageProvider
) -> List[HttpRoute]:
    """Turn fymo.yml's `storage.expose` entries into `HttpRoute`s. Returns
    `[]` when `expose_config` is empty, so apps without expose entries (the
    vast majority, pre-existing and new alike) register zero extra routes.
    `storage` is the already-constructed provider every route's handler
    resolves files through (see fymo.storage.registry.build_storage_provider,
    called by fymo/core/server.py before this).

    Raises `ValueError` for an entry missing `prefix` or `dir` (a plain
    KeyError at startup would point at the wrong place, this names the bad
    entry). A prefix colliding with a reserved fymo prefix only warns
    (printed, matching ConfigManager's own warning style in
    fymo/core/config.py) rather than raising, since it's a config smell
    worth flagging loudly, not a guaranteed misconfiguration fymo should
    refuse to boot over. An entry whose `dir` doesn't exist under the
    storage root yet also only warns, naming the resolved path: the
    directory may legitimately be created later (a job writing its first
    file into it), but until then every request under the prefix 404s, and
    that used to be silent."""
    routes: List[HttpRoute] = []
    for entry in expose_config:
        if "prefix" not in entry or "dir" not in entry:
            raise ValueError(
                f"storage.expose entry is missing required key(s) 'prefix' and/or 'dir': {entry!r}"
            )
        prefix = entry["prefix"]
        for reserved in _RESERVED_PREFIXES:
            if prefix.startswith(reserved) or reserved.startswith(prefix):
                print(
                    f"Warning: storage.expose prefix {prefix!r} overlaps with fymo's "
                    f"reserved {reserved!r} route, which is matched first and "
                    f"will always win. This exposed route may never be reached."
                )
        dir_key = str(entry["dir"]).strip("/")
        # Only providers with a filesystem root (local) can be checked for a
        # missing dir; a remote provider (S3/R2, once #17 lands) has no
        # directory to stat.
        root_dir = getattr(storage, "root_dir", None)
        if root_dir is not None and not (Path(root_dir) / dir_key).is_dir():
            print(
                f"Warning: storage.expose dir {entry['dir']!r} does not exist "
                f"under the storage root (resolved: {Path(root_dir) / dir_key}). "
                f"Requests under {prefix!r} will 404 until it is created."
            )
        extensions = {str(e).lower().lstrip(".") for e in entry.get("extensions", [])}
        routes.append(HttpRoute(
            method="GET",
            path=prefix,
            handler=_make_expose_handler(prefix, dir_key, extensions, storage),
        ))
    return routes
