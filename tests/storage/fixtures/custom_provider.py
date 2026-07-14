"""Minimal StorageProvider used only by tests/storage/test_registry.py, to
prove that a dotted `class:` config path produces a real, working provider
and not just something that passes isinstance()."""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from fymo.storage.base import BaseStorageProvider, RangeNotSatisfiable


class EchoStorageProvider(BaseStorageProvider):
    """In-memory provider: write() stores bytes in a dict, read() gives
    them back. No filesystem, no project_root, just enough surface to
    prove the registry actually built a usable instance."""

    def __init__(self) -> None:
        self._data: Dict[str, bytes] = {}

    def write(self, key: str, data: bytes) -> None:
        self._data[key] = data

    def read(self, key: str, range: Optional[Tuple[int, int]] = None) -> bytes:
        data = self._data[key]
        if range is None:
            return data
        start, end = range
        size = len(data)
        if start < 0 or start >= size or end < start:
            raise RangeNotSatisfiable(size)
        end = min(end, size - 1)
        return data[start:end + 1]

    def size(self, key: str) -> int:
        return len(self._data[key])

    def url_for(self, key: str) -> Optional[str]:
        return None

    def exists(self, key: str) -> bool:
        return key in self._data

    def delete(self, key: str) -> None:
        del self._data[key]
