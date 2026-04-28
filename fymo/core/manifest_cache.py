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

    def module_for_hash(self, hash: str) -> Optional[str]:
        """Return the remote-module name owning this hash, or None."""
        manifest = self.get()
        for name, asset in manifest.remote_modules.items():
            if asset.hash == hash:
                return name
        return None

    def get_remote_hash(self, module_name: str) -> Optional[str]:
        manifest = self.get()
        asset = manifest.remote_modules.get(module_name)
        return asset.hash if asset else None


# Set at FymoApp init time so html._remote_marker can find the hash without
# needing a reference threaded through every call site.
_SHARED_CACHE: "ManifestCache | None" = None


def set_shared_cache(cache: "ManifestCache | None") -> None:
    global _SHARED_CACHE
    _SHARED_CACHE = cache
