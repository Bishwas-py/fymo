"""Per-process manifest cache that auto-reloads on file change (dev hot-reload)."""
from pathlib import Path
from threading import Lock
from typing import Optional
from fymo.build.manifest import Manifest


class ManifestUnavailable(RuntimeError):
    """Raised when manifest.json doesn't exist (build hasn't run)."""


class ManifestCache:
    def __init__(self, dist_dir: Path):
        self.dist_dir = Path(dist_dir)
        self.path = self.dist_dir / "manifest.json"
        self._cached: Optional[Manifest] = None
        self._cached_mtime: Optional[float] = None
        self._lock = Lock()

    def get(self) -> Manifest:
        with self._lock:
            try:
                mtime = self.path.stat().st_mtime
            except FileNotFoundError:
                raise ManifestUnavailable(
                    f"{self.path} not found; run `fymo build` first"
                )

            if self._cached is None or mtime != self._cached_mtime:
                self._cached = Manifest.read(self.path)
                self._cached_mtime = mtime
                if self._cached is None:
                    raise ManifestUnavailable(f"failed to read {self.path}")
            return self._cached

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None
            self._cached_mtime = None
