"""Local-filesystem StorageProvider.

Ports the traversal-safe, symlink-safe containment check `fymo.core.media`
already uses for its `dir:`-configured routes, so a storage `key` (untrusted
input in exactly the same way a requested filename is) gets the same
guarantee: no `..` segment, no absolute-path override, and no symlink
planted inside root that resolves somewhere outside it. `_is_traversal_safe`
and `_resolve_within` are a direct port, not a reimplementation, of
`fymo.core.media`'s functions of the same name and behavior.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from fymo.storage.base import BaseStorageProvider, RangeNotSatisfiable


def _is_traversal_safe(key: str) -> bool:
    """Cheap first check: no '..' segments and no absolute path. Checked as
    plain substring/prefix tests, since `root_dir / key` would happily let a
    leading '/' override root_dir entirely (pathlib treats joining with an
    absolute path as a replacement, not a traversal). Not sufficient alone
    against a symlink physically planted inside root_dir that points
    elsewhere, which is what `_resolve_within` below is for."""
    return ".." not in key and not key.startswith("/")


def _resolve_within(root_dir: Path, key: str) -> Optional[Path]:
    """Join `key` onto `root_dir` and confirm the fully-resolved path,
    symlinks included, is still contained within `root_dir`. Returns None if
    it escapes. `root_dir` is assumed already resolved."""
    candidate = (root_dir / key).resolve()
    if candidate != root_dir and not candidate.is_relative_to(root_dir):
        return None
    return candidate


class LocalStorageProvider(BaseStorageProvider):
    """Stores blobs directly on disk under `root` (relative to
    `project_root`), or under `project_root` itself when `root` is unset.
    That default is what lets `storage: {provider: local}` with no `root:`
    key behave identically to resolving straight against `project_root`."""

    def __init__(self, root: Optional[str] = None, *, project_root: Path):
        base = Path(project_root) / root if root else Path(project_root)
        self.root_dir = base.resolve()

    def _resolve(self, key: str) -> Path:
        if not _is_traversal_safe(key):
            raise ValueError(f"unsafe storage key: {key!r}")
        resolved = _resolve_within(self.root_dir, key)
        if resolved is None:
            raise ValueError(f"unsafe storage key: {key!r}")
        return resolved

    def write(self, key: str, data: bytes) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read(self, key: str, range: Optional[Tuple[int, int]] = None) -> bytes:
        path = self._resolve(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        if range is None:
            return path.read_bytes()

        start, end = range
        file_size = path.stat().st_size
        # Unsatisfiable per RFC 7233 section 2.1: start at/past EOF, or an
        # end before start. `end` running past EOF is not itself an error,
        # it's clamped below, matching fymo.core.media's existing behavior.
        if start < 0 or start >= file_size or end < start:
            raise RangeNotSatisfiable(file_size)
        end = min(end, file_size - 1)

        with open(path, "rb") as f:
            f.seek(start)
            return f.read(end - start + 1)

    def size(self, key: str) -> int:
        path = self._resolve(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.stat().st_size

    def url_for(self, key: str) -> Optional[str]:
        # Local storage has no directly-servable URL; callers proxy through
        # the app (the media route handler, for instance).
        return None

    def exists(self, key: str) -> bool:
        path = self._resolve(key)
        return path.is_file()

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        path.unlink()
