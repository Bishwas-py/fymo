"""The StorageProvider seam.

Every place fymo needs to put or get a blob of bytes (declarative
`storage.expose` serving today, app-written uploads/generated files tomorrow) goes through
one of these instead of hardcoding a filesystem path. A provider owns where
`key` (a namespaced relative path, e.g. "videos/foo.webm") actually lives:
local disk, S3, or anything else a `class:` config entry points at.

Unlike auth's providers (several installed at once, each contributing only
the hooks it cares about), storage has exactly one active provider per app,
and every method below is load-bearing, none of it is optional the way
auth's remote_functions()/http_routes() are. `BaseStorageProvider` still
exists for a consistent shape and an isinstance-friendly base, but its
defaults raise rather than silently no-op, except `url_for`, which is
genuinely optional: most providers (local disk) have nothing to return.
"""
from __future__ import annotations

from typing import Optional, Protocol, Tuple, runtime_checkable


class RangeNotSatisfiable(Exception):
    """Raised by read() when the requested byte range falls outside the
    object's actual size. Carries `size` so callers can build the RFC 7233
    416 response's `Content-Range: bytes */<size>` header without a second
    round-trip to the provider just to look up the size."""

    def __init__(self, size: int):
        super().__init__(f"range not satisfiable, object size is {size}")
        self.size = size


@runtime_checkable
class StorageProvider(Protocol):
    def write(self, key: str, data: bytes) -> None: ...
    def read(self, key: str, range: Optional[Tuple[int, int]] = None) -> bytes: ...
    def size(self, key: str) -> int: ...
    def url_for(self, key: str) -> Optional[str]: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...


class BaseStorageProvider:
    """Inert base class. Subclass and override every method; the
    NotImplementedError defaults exist so a half-finished or test-double
    provider fails loudly at the call site instead of silently returning
    empty bytes or a size of zero."""

    def write(self, key: str, data: bytes) -> None:
        raise NotImplementedError

    def read(self, key: str, range: Optional[Tuple[int, int]] = None) -> bytes:
        raise NotImplementedError

    def size(self, key: str) -> int:
        raise NotImplementedError

    def url_for(self, key: str) -> Optional[str]:
        return None

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError
