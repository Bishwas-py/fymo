"""
Asset management for Fymo applications
"""

import mimetypes
from pathlib import Path
from typing import Dict, Tuple, Optional



class AssetManager:
    """Manages compiled assets and static files for Fymo applications"""

    def __init__(self, project_root: Path):
        """
        Initialize asset manager

        Args:
            project_root: Root directory of the project
        """
        self.project_root = project_root

    @staticmethod
    def _safe_resolve(root: Path, rel_path: str) -> Optional[Path]:
        """Resolve ``rel_path`` under ``root``, returning the target path only if
        it stays inside ``root``. Returns ``None`` for any traversal attempt.

        Blocks three primitives at once:
          * null bytes,
          * ``..`` path segments,
          * absolute operands (leading ``/``), which pathlib would otherwise use
            to reset the join (``root / "/etc/passwd"`` == ``Path("/etc/passwd")``).
        A final ``relative_to`` check is defence-in-depth against symlinks and any
        residual escape after resolution.
        """
        if "\x00" in rel_path:
            return None
        # Strip leading slashes so an absolute operand can't reset the join.
        rel_path = rel_path.lstrip("/")
        if ".." in rel_path.split("/"):
            return None

        root = root.resolve()
        target = (root / rel_path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return None
        return target

    @staticmethod
    def _etag_matches(if_none_match: str, etag: str) -> bool:
        """True when the request's If-None-Match header matches `etag`.

        Weak comparison (the W/ prefix is ignored), which is what RFC 9110
        prescribes for If-None-Match; `*` matches any current representation.
        """
        for candidate in if_none_match.split(","):
            candidate = candidate.strip()
            if candidate.startswith("W/"):
                candidate = candidate[2:]
            if candidate == "*" or candidate == etag:
                return True
        return False

    def serve_static_file(
        self, rel_path: str, environ: Optional[dict] = None
    ) -> Tuple[bytes, str, str, Dict[str, str]]:
        """Serve a file from app/static verbatim, as bytes.

        `rel_path` is the path relative to app/static/ (the part of the URL
        after the /static/ prefix). Static files are unhashed, so responses
        carry an ETag (from stat mtime+size) and If-None-Match is honored
        with a 304 -- the 1-hour Cache-Control alone would re-download the
        full body on every expiry.
        """
        static_path = self._safe_resolve(self.project_root / 'app' / 'static', rel_path)
        if static_path is None:
            return b"Forbidden", "403 FORBIDDEN", "text/plain", {}

        if static_path.exists() and static_path.is_file():
            content_type, _ = mimetypes.guess_type(str(static_path))
            if not content_type:
                content_type = 'application/octet-stream'

            try:
                stat = static_path.stat()
                etag = '"%x-%x"' % (stat.st_mtime_ns, stat.st_size)
                headers = {"ETag": etag, "Cache-Control": "public, max-age=3600"}
                if_none_match = (environ or {}).get("HTTP_IF_NONE_MATCH", "")
                if if_none_match and self._etag_matches(if_none_match, etag):
                    return b"", "304 NOT MODIFIED", content_type, headers
                return static_path.read_bytes(), "200 OK", content_type, headers
            except IOError:
                return b"Error reading file", "500 INTERNAL SERVER ERROR", "text/plain", {}

        return b"File not found", "404 NOT FOUND", "text/plain", {}

    def serve_dist_asset(self, path: str) -> Tuple[bytes, str, str, Dict[str, str]]:
        """Serve a file from <project>/dist/. Returns (body, status, content_type, extra_headers).

        path: the part after /dist/ (e.g. "client/todos.A1B2.js")
        """
        target = self._safe_resolve(self.project_root / "dist", path)
        if target is None:
            return b"forbidden", "403 FORBIDDEN", "text/plain", {}

        if not target.is_file():
            return b"not found", "404 NOT FOUND", "text/plain", {}

        content_type, _ = mimetypes.guess_type(str(target))
        if content_type is None:
            content_type = "application/octet-stream"
        # Normalise JavaScript MIME type; older systems report text/javascript
        if content_type in ("text/javascript", "application/x-javascript"):
            content_type = "application/javascript"

        # Hashed filenames (anything in client/) get long-cache; manifest.json gets no-cache
        if path == "manifest.json":
            cache = "no-cache"
        else:
            cache = "public, max-age=31536000, immutable"

        return target.read_bytes(), "200 OK", content_type, {"Cache-Control": cache}
